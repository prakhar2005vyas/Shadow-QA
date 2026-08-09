"""
Fireworks AI client — used ONLY for the text report-writing step.

Design rules (from spec):
  - This is the ONLY place Fireworks AI is called.
  - Vision/decision ALWAYS uses vlm_client.py → AMD vLLM. Never Fireworks.
  - Phase 0: returns a stub if FIREWORKS_API_KEY is not set.
  - Phase 2: compiler.py will call generate_report_text() instead of its plain-text fallback.

The separation between AMD (vision) and Fireworks (report writing) is intentional,
architecturally distinct, and documented in README.md.
"""

import logging
import os

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from ..config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TEST_NAME = "shadow-qa-run"


def _gateway_headers() -> dict[str, str]:
    """
    Build common HTTP headers for every Fireworks (reporting) gateway request.

    X-Test-Name is stamped by the pytest conftest fixture during test execution.
    Outside pytest the env var is absent and the call falls back to the
    service-level default — no KeyError, no crash.
    """
    return {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
        "X-Test-Name": os.getenv("LLM_GATEWAY_TEST_NAME", _DEFAULT_TEST_NAME),
    }


# Reporting endpoint routes through the same OpenAI-compatible gateway as the VLM.
# Override via OPENAI_BASE_URL in the environment (e.g. point at a LiteLLM proxy).


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def generate_report_text(
    bug_description: str,
    severity: str,
    category: str,
    action_trail: list[str],
) -> str:
    """
    Call Fireworks AI to generate a polished, human-readable bug report.

    NOTE: This is the ONLY function that calls Fireworks AI.
          It is NEVER called from vlm_client.py or agent/loop.py.

    Args:
        bug_description: Raw anomaly description from the VLM.
        severity: "low" | "medium" | "high" | "critical"
        category: One of the Anomaly.category literals.
        action_trail: Recent action history for reproduction context.

    Returns:
        Markdown-formatted bug report string.

    Raises:
        httpx.HTTPStatusError: If Fireworks returns an error after retries.
    """
    # Gateway key is always present (has a default), so no stub guard needed.
    # If MOCK_VLM=true the agent loop never reaches this function anyway.

    trail_text = "\n".join(f"- {a}" for a in action_trail[-5:]) or "_(no prior actions)_"
    prompt = f"""You are a senior QA engineer writing a structured bug report for a development team.
Based on the information below, write a clear, concise, actionable bug report in markdown.

**Bug description:** {bug_description}
**Severity:** {severity}
**Category:** {category}
**Recent actions before bug was found:**
{trail_text}

Write the report with these sections:
1. One-line title (as a level-2 heading)
2. 2-3 sentence executive summary
3. Numbered step-by-step reproduction steps
4. Expected vs. actual behaviour
5. Suggested fix or investigation direction

Keep it concise. Do not add a preamble or closing remarks."""

    payload = {
        "model": settings.fireworks_model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.openai_base_url}/chat/completions",
            json=payload,
            headers=_gateway_headers(),
        )
        response.raise_for_status()

    return response.json()["choices"][0]["message"]["content"]
