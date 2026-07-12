"""
Main agent loop.

Runs the full perception-decision-action cycle:
  1. Navigate to target URL
  2. For each step (bounded by MAX_STEPS and MAX_SECONDS):
     a. Screenshot
     b. Summarise DOM
     c. Compute a state ID (URL + structural DOM fingerprint) for loop prevention —
        if this exact state was already fully explored, force a go_back and skip
        the VLM call entirely; if it's a repeat but not exhausted, warn the model
        in the prompt instead of letting it wander back into the same loop
     d. Call VLM → AgentStep
     e. Record Finding if anomaly detected
     f. Fuzz the fill value some of the time (agent/fuzzing.py)
     g. Record action in history, persist this step
     h. Break if type=="stop" or budgets exceeded
     i. Execute next_action
  3. Compile findings → Reports
  4. Update Run status in DB

This function is called from the background task in routes/runs.py.
It is designed to never raise — all errors are caught, logged, and
surfaced as run.status="failed" or step "inconclusive".
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime

from sqlmodel import Session

from ..config import settings
from ..models import Run, Finding, Step
from .browser import BrowserSession
from .fuzzing import get_fuzz_payload, should_fuzz
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
    "defects, genuine accessibility violations). "
    "\n\nAct as a meticulous visual QA tester, not just a functional one. On every "
    "screenshot, specifically look for: layout shifting, misaligned grids, and "
    "overlapping text or buttons; stuck loading spinners or infinite progress bars "
    "that never resolve; contrast and accessibility failures such as clipped/cut-off "
    "elements or text whose color is unreadable against its background; and broken "
    "image assets or missing UI components (blank space where a button, icon, or "
    "widget should be). Use category 'visual_layout' for layout/overlap/spinner "
    "issues, 'accessibility' for contrast/clipping issues, and 'other' for broken "
    "assets/missing components that don't fit those two."
)

# ---------------------------------------------------------------------------
# State memory graph (loop prevention)
# ---------------------------------------------------------------------------
# Lightweight, pure-stdlib (hashlib + re) fingerprinting — no extra Playwright
# calls, no new dependencies. A "state" is (current URL, structural shape of
# the interactive-elements list), deliberately ignoring the parts of the DOM
# summary that change on their own between visits to the *same* state:
# the numeric data-shadow-id values (stable per element, but not guaranteed to
# renumber identically across a fresh page load) and the [ALREADY_TRIED]
# markers (which change as tried_selectors grows, even though the underlying
# page hasn't).
_SHADOW_ID_RE = re.compile(r"\[data-shadow-id='\d+'\]")
_ALREADY_TRIED_RE = re.compile(r"\s*\[ALREADY_TRIED\]")


def _compute_state_id(url: str, dom_summary: str) -> str:
    normalized = _SHADOW_ID_RE.sub("[data-shadow-id]", dom_summary)
    normalized = _ALREADY_TRIED_RE.sub("", normalized)
    fingerprint = f"{url}|{normalized}"
    return hashlib.md5(fingerprint.encode()).hexdigest()[:12]


def _is_state_exhausted(dom_summary: str) -> bool:
    """True if every interactive element on this page has already been tried."""
    if dom_summary.strip() in ("(no interactive elements found)", "(DOM summary unavailable)"):
        return True
    lines = [line for line in dom_summary.splitlines() if line.strip()]
    return bool(lines) and all("[ALREADY_TRIED]" in line for line in lines)


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
    # State memory graph for loop prevention: state_id -> number of visits.
    state_visit_counts: dict[str, int] = {}
    cancelled = False

    try:
        async with BrowserSession() as browser:
            navigated = await browser.navigate(target_url)

            if not navigated:
                # Target is completely unreachable (connection refused, DNS failure,
                # hard timeout) — there's no page to explore, so record one critical
                # finding and fall through to the normal compile/complete path below
                # instead of running the step loop against a browser error page.
                logger.error(
                    "Run %d — target URL %r is unreachable; recording a critical "
                    "finding and concluding the run",
                    run_id,
                    target_url,
                )
                step_count = 1
                unreachable_msg = (
                    f"Target URL '{target_url}' could not be reached at all — the "
                    "browser's initial navigation failed (connection refused, DNS "
                    "failure, or a hard navigation timeout). No page ever loaded, so "
                    "no exploration was possible."
                )
                db_session.add(
                    Step(
                        run_id=run_id,
                        step_num=0,
                        observation=unreachable_msg,
                        is_anomaly=True,
                        action_type="stop",
                        action_selector=None,
                        action_reason="target URL unreachable",
                        screenshot_b64=None,
                    )
                )
                finding = Finding(
                    run_id=run_id,
                    step_num=0,
                    description=unreachable_msg,
                    severity="critical",
                    category="error_state",
                    screenshot_b64=None,
                )
                db_session.add(finding)
                db_session.commit()
                logger.info(
                    "Run %d — finding #%d recorded: [critical] target unreachable",
                    run_id,
                    finding.id,
                )

            for step_index in range(settings.max_steps_per_run if navigated else 0):
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

                # ---- cancellation check ----
                # POST /runs/{id}/cancel runs in a *different* DB session/request,
                # so db_session.refresh() forces a real SELECT here rather than
                # relying on this long-lived session's identity map (which could
                # otherwise keep serving the stale in-memory `run` object).
                db_session.refresh(run)
                if run.status == "cancelled":
                    logger.info(
                        "Run %d cancelled by user request at step %d", run_id, step_index
                    )
                    cancelled = True
                    break

                step_count += 1
                logger.info(
                    "Run %d — step %d — url=%s",
                    run_id,
                    step_index,
                    browser.current_url,
                )

                # a. screenshot — never raises; returns None if the page hung
                # Playwright's screenshot call twice in a row (see browser.py).
                screenshot_b64 = await browser.screenshot_b64()
                if screenshot_b64 is None:
                    logger.warning(
                        "Run %d step %d — screenshot unavailable after retry, skipping VLM call for this step",
                        run_id,
                        step_index,
                    )
                    action_history.append(f"step {step_index}: [inconclusive — screenshot timeout]")
                    db_session.add(
                        Step(
                            run_id=run_id,
                            step_num=step_index,
                            observation="Screenshot capture timed out twice — this step is inconclusive.",
                            is_anomaly=False,
                            action_type="skipped",
                            action_selector=None,
                            action_reason="screenshot timeout",
                            screenshot_b64=None,
                        )
                    )
                    db_session.commit()
                    await asyncio.sleep(0.5)
                    continue

                # b. DOM summary (elements already acted on are flagged [ALREADY_TRIED])
                dom_summary = await browser.summarize_elements(tried_selectors)

                # b2. state memory graph — has the agent been in this exact state
                # (same URL + same structural set of interactive elements) before?
                state_id = _compute_state_id(browser.current_url, dom_summary)
                state_visit_counts[state_id] = state_visit_counts.get(state_id, 0) + 1
                is_repeat_state = state_visit_counts[state_id] > 1

                if is_repeat_state and _is_state_exhausted(dom_summary):
                    # Every element at this state has already been tried and we've
                    # looped back to it anyway — force a go_back instead of spending
                    # a VLM call asking a question we already know the answer to.
                    logger.info(
                        "Run %d step %d — state %s exhausted (visit #%d), forcing go_back",
                        run_id,
                        step_index,
                        state_id,
                        state_visit_counts[state_id],
                    )
                    forced_action = NextAction(
                        type="go_back",
                        selector=None,
                        value=None,
                        reason="[LOOP PREVENTION] all elements at this state already tried",
                    )
                    action_history.append(
                        f"step {step_index}: go_back — [LOOP PREVENTION] state {state_id} exhausted"
                    )
                    db_session.add(
                        Step(
                            run_id=run_id,
                            step_num=step_index,
                            observation=f"Loop prevention: state {state_id} fully exhausted, forcing go_back.",
                            is_anomaly=False,
                            action_type="go_back",
                            action_selector=None,
                            action_reason=forced_action.reason,
                            screenshot_b64=screenshot_b64,
                        )
                    )
                    db_session.commit()
                    result = await browser.execute_action(forced_action)
                    logger.info("Run %d step %d action result: %s", run_id, step_index, result)
                    await asyncio.sleep(0.5)
                    continue

                # If we've seen this state before but it's not exhausted yet, tell the
                # model explicitly rather than letting it wander back into a loop.
                step_goal = GOAL
                if is_repeat_state:
                    step_goal = (
                        f"{GOAL}\n\nIMPORTANT: you have been in this exact page state "
                        f"before (visit #{state_visit_counts[state_id]}). Do not repeat an "
                        f"action you've already tried here — choose an element WITHOUT the "
                        f"[ALREADY_TRIED] marker."
                    )

                # b3. console/network activity since the last action — many bugs (JS
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
                    goal=step_goal,
                    action_history=action_history,
                    current_url=browser.current_url,
                    previously_reported_anomalies=reported_anomalies,
                    console_errors=new_console_errors,
                    network_errors=new_network_errors,
                )

                if is_inconclusive:
                    logger.warning("Run %d step %d is inconclusive — continuing", run_id, step_index)
                    action_history.append(f"step {step_index}: [inconclusive — VLM error]")
                    db_session.add(
                        Step(
                            run_id=run_id,
                            step_num=step_index,
                            observation=agent_step.observation,
                            is_anomaly=False,
                            action_type=agent_step.next_action.type,
                            action_selector=agent_step.next_action.selector,
                            action_reason=agent_step.next_action.reason,
                            screenshot_b64=screenshot_b64,
                        )
                    )
                    db_session.commit()
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

                # e. input fuzzing — some fraction of fill actions get the model's
                # chosen value swapped for a random edge-case payload (long strings,
                # SQL-injection characters, emoji, whitespace, invalid formats) to
                # exercise the target's input validation and error handling. Kept
                # probabilistic (not every fill) so the agent still explores what
                # happens after a normal, valid form submission too.
                action = agent_step.next_action
                fuzz_note = ""
                if action.type == "fill" and action.selector and should_fuzz():
                    fuzz_category, fuzz_payload = get_fuzz_payload()
                    original_value = action.value
                    action = action.model_copy(update={"value": fuzz_payload})
                    fuzz_note = f" [FUZZED:{fuzz_category}]"
                    logger.info(
                        "Run %d step %d — fuzzing fill on %s: category=%s (model wanted %r)",
                        run_id,
                        step_index,
                        action.selector,
                        fuzz_category,
                        original_value,
                    )

                # f. record action in history — includes the actual value filled
                # (post-fuzz, if fuzzed) so reproduction steps stay honest about
                # what was really injected, not what the model merely intended.
                action_history.append(
                    f"step {step_index}: {action.type}"
                    + (f" {action.selector}" if action.selector else "")
                    + (f" = {action.value!r}" if action.type == "fill" else "")
                    + fuzz_note
                    + f" — {action.reason}"
                )
                if action.selector:
                    tried_selectors.add(action.selector)

                # d2. persist this step (every step, not just anomaly ones) so the
                # live agent view can poll step-by-step progress while the run is
                # still in progress — Finding alone only covers anomaly steps.
                db_session.add(
                    Step(
                        run_id=run_id,
                        step_num=step_index,
                        observation=agent_step.observation,
                        is_anomaly=agent_step.anomaly is not None,
                        action_type=action.type,
                        action_selector=action.selector,
                        action_reason=action.reason,
                        screenshot_b64=screenshot_b64,
                    )
                )
                db_session.commit()

                # g. stop if requested
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
            # Don't stomp the 'cancelled' status the /cancel endpoint already set —
            # only mark 'completed' if the loop ended on its own terms.
            if not cancelled:
                run_final.status = "completed"
            run_final.completed_at = datetime.utcnow()
            run_final.total_steps = step_count
            db_session.add(run_final)
            db_session.commit()

        logger.info(
            "Run %d %s — %d steps, findings stored",
            run_id,
            "cancelled" if cancelled else "completed",
            step_count,
        )

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
