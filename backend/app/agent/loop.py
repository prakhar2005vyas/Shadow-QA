"""
Main agent loop.

Runs the full perception-decision-action cycle:
  1. Navigate to target URL
  2. For each step (bounded by MAX_STEPS and MAX_SECONDS):
     a. Screenshot
     b. Summarise DOM
     c. Call VLM → AgentStep
     d. Record Finding if anomaly detected
     e. Execute next_action
     f. Break if type=="stop" or budgets exceeded
  3. Compile findings → Reports
  4. Update Run status in DB

This function is called from the background task in routes/runs.py.
It is designed to never raise — all errors are caught, logged, and
surfaced as run.status="failed" or step "inconclusive".
"""

import asyncio
import json
import logging
import time
from datetime import datetime

from sqlmodel import Session

from ..config import settings
from ..models import Run, Finding
from .browser import BrowserSession
from .vlm_client import call_vlm
from .schemas import NextAction

logger = logging.getLogger(__name__)

GOAL = (
    "Explore this web application as a QA tester would. "
    "Click interactive elements, submit forms, scroll the page, and follow links. "
    "Look for broken buttons, JavaScript errors, layout issues, dead links, "
    "missing images, low-contrast text, and accessibility problems. "
    "Report every anomaly you observe. "
    "If an action leads to an error page (404, blank page) or otherwise breaks the "
    "page, that IS the anomaly to report — but it is not a reason to stop the run. "
    "Use next_action.type='go_back' to return to the previous page and keep exploring "
    "the rest of the site. "
    "You MUST interact with every single button, link, and form field visible on the "
    "page (including any revealed by scrolling) at least once before you are allowed "
    "to issue next_action.type='stop'. Elements you have already interacted with are "
    "marked '[ALREADY_TRIED]' directly in the interactive-elements list below — only "
    "issue 'stop' once every element in that list carries that marker. "
    "This is a marketing site — hyperbolic or self-deprecating marketing copy (e.g. "
    "'Trusted by zero companies worldwide') is a deliberate content/design choice, not "
    "a bug. Do not report copywriting tone as an anomaly; only report things that are "
    "actually broken (errors, dead links, non-functional controls, real visual/layout "
    "defects, genuine accessibility violations)."
)


async def run_agent(run_id: int, target_url: str, db_session: Session) -> None:
    """
    Main agent loop. Mutates the Run record in db_session.
    Never raises — all errors surface as run.status='failed'.
    """
    # ------------------------------------------------------------------ #
    #  Mark run as running                                                 #
    # ------------------------------------------------------------------ #
    run = db_session.get(Run, run_id)
    if not run:
        logger.error("run_agent called with unknown run_id=%d", run_id)
        return

    run.status = "running"
    db_session.add(run)
    db_session.commit()

    action_history: list[str] = []
    tried_selectors: set[str] = set()
    reported_anomalies: list[str] = []
    console_watermark = 0
    network_watermark = 0
    step_count = 0
    start_time = time.monotonic()

    try:
        async with BrowserSession() as browser:
            await browser.navigate(target_url)

            for step_index in range(settings.max_steps_per_run):
                # ---- wall-clock budget ----
                elapsed = time.monotonic() - start_time
                if elapsed > settings.max_seconds_per_run:
                    logger.info(
                        "Run %d hit time budget (%.0fs / %ds)",
                        run_id,
                        elapsed,
                        settings.max_seconds_per_run,
                    )
                    break

                step_count += 1
                logger.info(
                    "Run %d — step %d — url=%s",
                    run_id,
                    step_index,
                    browser.current_url,
                )

                # a. screenshot
                screenshot_b64 = await browser.screenshot_b64()

                # b. DOM summary (elements already acted on are flagged [ALREADY_TRIED])
                dom_summary = await browser.summarize_elements(tried_selectors)

                # b2. console/network activity since the last action — many bugs (JS
                # errors, failed API calls) are invisible in a screenshot, so this is
                # fed to the model as ground truth alongside the image.
                all_console = browser.console_errors
                all_network = browser.network_errors
                new_console_errors = all_console[console_watermark:]
                new_network_errors = all_network[network_watermark:]
                console_watermark = len(all_console)
                network_watermark = len(all_network)

                # c. call VLM (mock or real)
                agent_step, is_inconclusive = await call_vlm(
                    step_index=step_index,
                    screenshot_b64=screenshot_b64,
                    dom_summary=dom_summary,
                    goal=GOAL,
                    action_history=action_history,
                    current_url=browser.current_url,
                    previously_reported_anomalies=reported_anomalies,
                    console_errors=new_console_errors,
                    network_errors=new_network_errors,
                )

                if is_inconclusive:
                    logger.warning("Run %d step %d is inconclusive — continuing", run_id, step_index)
                    action_history.append(f"step {step_index}: [inconclusive — VLM error]")
                    continue

                # d. record finding if an anomaly was detected
                if agent_step.anomaly:
                    finding = Finding(
                        run_id=run_id,
                        step_num=step_index,
                        description=agent_step.anomaly.description,
                        severity=agent_step.anomaly.severity,
                        category=agent_step.anomaly.category,
                        screenshot_b64=screenshot_b64,
                        console_errors_json=json.dumps(browser.console_errors),
                        network_errors_json=json.dumps(browser.network_errors),
                        action_trail_json=json.dumps(action_history),
                    )
                    db_session.add(finding)
                    db_session.commit()
                    logger.info(
                        "Run %d — finding #%d recorded: [%s] %s",
                        run_id,
                        finding.id,
                        agent_step.anomaly.severity,
                        agent_step.anomaly.description[:80],
                    )
                    reported_anomalies.append(
                        f"[{agent_step.anomaly.category}] {agent_step.anomaly.description}"
                    )

                # e. record action in history
                action = agent_step.next_action
                action_history.append(
                    f"step {step_index}: {action.type}"
                    + (f" {action.selector}" if action.selector else "")
                    + f" — {action.reason}"
                )
                if action.selector:
                    tried_selectors.add(action.selector)

                # f. stop if requested
                if action.type == "stop":
                    logger.info("Run %d received stop action at step %d", run_id, step_index)
                    break

                # Execute the action
                result = await browser.execute_action(action)
                logger.info("Run %d step %d action result: %s", run_id, step_index, result)

                # Small pause to let animations/fetches settle
                await asyncio.sleep(0.5)

        # ------------------------------------------------------------------ #
        #  Compile findings → reports                                         #
        # ------------------------------------------------------------------ #
        from ..reporting.compiler import compile_findings

        await compile_findings(run_id, db_session)

        # ------------------------------------------------------------------ #
        #  Mark run completed                                                 #
        # ------------------------------------------------------------------ #
        run_final = db_session.get(Run, run_id)
        if run_final:
            run_final.status = "completed"
            run_final.completed_at = datetime.utcnow()
            run_final.total_steps = step_count
            db_session.add(run_final)
            db_session.commit()

        logger.info("Run %d completed — %d steps, findings stored", run_id, step_count)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Run %d failed with unhandled exception: %s", run_id, exc)
        try:
            run_err = db_session.get(Run, run_id)
            if run_err:
                run_err.status = "failed"
                run_err.error_msg = str(exc)
                run_err.completed_at = datetime.utcnow()
                run_err.total_steps = step_count
                db_session.add(run_err)
                db_session.commit()
        except Exception as inner:
            logger.error("Failed to update run status after error: %s", inner)
