"""
VLM client — routes to mock_vlm (MOCK_VLM=true) or the real AMD vLLM endpoint.

Design rules (from spec):
  - Vision/decision ALWAYS goes through this file → AMD vLLM (or mock).
  - Fireworks AI is NEVER called here.
  - Model ID, base URL, and API key are always read from settings (never hardcoded).
  - On repeated failure: mark step inconclusive and continue the run, don't crash.
"""

import logging
import time
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from ..config import settings
from .schemas import AgentStep, NextAction
from .mock_vlm import get_mock_step

logger = logging.getLogger(__name__)


def _build_prompt(
    dom_summary: str,
    goal: str,
    action_history: list[str],
    previously_reported_anomalies: Optional[list[str]] = None,
    console_errors: Optional[list[str]] = None,
    network_errors: Optional[list[str]] = None,
) -> str:
    history_text = (
        "\n".join(f"  {i + 1}. {a}" for i, a in enumerate(action_history))
        if action_history
        else "  (none yet)"
    )
    anomalies_text = (
        "\n".join(f"  - {a}" for a in previously_reported_anomalies)
        if previously_reported_anomalies
        else "  (none yet)"
    )
    console_text = (
        "\n".join(f"  - {c}" for c in console_errors)
        if console_errors
        else "  (none since your last action)"
    )
    network_text = (
        "\n".join(f"  - {n}" for n in network_errors)
        if network_errors
        else "  (none since your last action)"
    )
    schema = AgentStep.model_json_schema()
    return (
        f"You are a QA agent.\n\nGoal: {goal}\n\n"
        f"Visible interactive elements:\n{dom_summary}\n\n"
        "Each line above is formatted as: selector=\"[data-shadow-id='N']\" | tag#id.cls | "
        "\"visible text\" href. The selector is a unique, per-element id (e.g. "
        "selector=\"[data-shadow-id='3']\" | button.btn-primary | \"Send Message\") — it is "
        "guaranteed to match exactly one element on the page, even when several elements "
        "share the same tag and class. When you choose to click/fill an element, "
        "next_action.selector MUST be an exact copy of the string inside the double quotes "
        "that immediately follow 'selector=' on that element's line — nothing else from the "
        "line, and nothing you invent yourself. Never construct your own tag/class-based "
        "selector.\n\n"
        f"Action history:\n{history_text}\n\n"
        f"Already-reported anomalies (do NOT report any of these again — set 'anomaly' to "
        f"null if the only defect visible right now is already in this list; only report "
        f"a NEW, distinct defect not covered here):\n{anomalies_text}\n\n"
        f"Browser console errors/warnings since your last action:\n{console_text}\n\n"
        f"Failed network requests since your last action:\n{network_text}\n\n"
        "Reminder: a real QA engineer doesn't just look at the screen — they check the "
        "browser console and network tab too. Many real bugs are completely invisible in "
        "a screenshot: a JS error thrown by a broken onclick handler, or a form submission "
        "whose request 404s in the background, produce NO visible change on the page at "
        "all. Treat the console/network logs above as ground truth, not the screenshot: if "
        "they show a new error or failed request resulting from the action you just took, "
        "that IS a real anomaly to report — even if the page looks completely unchanged. "
        "Use category 'broken_interaction' for a console error caused by clicking/filling "
        "an element, and 'error_state' for a failed network request (e.g. a form POST that "
        "404s).\n\n"
        "Reminder: hitting an error page or a broken element is something to report as "
        "an anomaly, not a reason to stop. Prefer 'go_back' over 'stop' unless you have "
        "already explored this page thoroughly or are only revisiting prior ground.\n\n"
        "Reminder: elements in 'Visible interactive elements' above that already carry the "
        "'[ALREADY_TRIED]' marker have been interacted with in a previous step — prefer "
        "acting on an element WITHOUT that marker. You must not choose "
        "next_action.type='stop' while any element in that list lacks the marker.\n\n"
        "Respond ONLY with a single valid JSON object matching this schema:\n"
        f"{schema}\n\n"
        "Do not include any text outside the JSON object."
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _call_real_vlm(
    screenshot_b64: str,
    dom_summary: str,
    goal: str,
    action_history: list[str],
    previously_reported_anomalies: Optional[list[str]] = None,
    console_errors: Optional[list[str]] = None,
    network_errors: Optional[list[str]] = None,
) -> AgentStep:
    """Call the AMD-hosted vLLM endpoint with structured-output constraints."""
    prompt = _build_prompt(
        dom_summary,
        goal,
        action_history,
        previously_reported_anomalies,
        console_errors,
        network_errors,
    )

    payload = {
        "model": settings.vlm_model_id,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 512,
        "temperature": 0.1,
        # response_format (OpenAI/Ollama standard) replaces guided_json (vLLM-only) for local Ollama compatibility
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "AgentStep",
                "schema": AgentStep.model_json_schema(),
                "strict": True,
            },
        },
    }

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.vlm_base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {settings.vlm_api_key}"},
        )
        response.raise_for_status()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info("[vlm] step latency: %.0fms  model=%s", elapsed_ms, settings.vlm_model_id)

    raw_content: str = response.json()["choices"][0]["message"]["content"]
    logger.debug("VLM raw response: %s", raw_content[:300])

    return _parse_agent_step(raw_content)


def _parse_agent_step(raw: str) -> AgentStep:
    """
    Parse an AgentStep from the VLM response string.

    Primary path: model returned clean JSON (expected with guided_json).
    Fallback: strip markdown code fences (```json ... ```) and retry.
    This handles the rare case where a model adds decorations despite guidance.
    """
    # Try direct parse first
    try:
        return AgentStep.model_validate_json(raw)
    except Exception:
        pass

    # Fallback: extract JSON from markdown code block if present
    import re
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return AgentStep.model_validate_json(match.group(1))
        except Exception:
            pass

    # Last resort: find first { ... } substring
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return AgentStep.model_validate_json(raw[start:end])
        except Exception:
            pass

    raise ValueError(f"Could not parse AgentStep from VLM response: {raw[:200]!r}")


async def call_vlm(
    step_index: int,
    screenshot_b64: str,
    dom_summary: str,
    goal: str,
    action_history: list[str],
    current_url: str,
    previously_reported_anomalies: Optional[list[str]] = None,
    console_errors: Optional[list[str]] = None,
    network_errors: Optional[list[str]] = None,
) -> tuple[AgentStep, bool]:
    """
    Call the VLM (mock or real).

    Returns:
        (agent_step, is_inconclusive)
        is_inconclusive=True means the call failed after retries — the loop should
        log 'inconclusive' and continue rather than crashing the whole run.
    """
    if settings.mock_vlm:
        logger.info("[MOCK VLM] step=%d url=%s", step_index, current_url)
        return get_mock_step(step_index, current_url, dom_summary), False

    logger.info("[VLM] step=%d url=%s model=%s", step_index, current_url, settings.vlm_model_id)
    try:
        step = await _call_real_vlm(
            screenshot_b64,
            dom_summary,
            goal,
            action_history,
            previously_reported_anomalies,
            console_errors,
            network_errors,
        )
        return step, False
    except Exception as exc:
        logger.error("VLM call failed after retries at step %d: %s", step_index, exc)
        inconclusive_step = AgentStep(
            observation=f"VLM call failed — step {step_index} is inconclusive. Error: {exc}",
            anomaly=None,
            next_action=NextAction(
                type="stop",
                selector=None,
                value=None,
                reason=f"VLM error: {exc}",
            ),
        )
        return inconclusive_step, True
