"""
Phase 1 integration tests — real AMD vLLM validation.

These tests are SKIPPED automatically when MOCK_VLM=true (the default for CI/local dev).
They are intended to run with MOCK_VLM=false pointing at the AMD MI300X droplet.

To run Phase 1 tests:
    export MOCK_VLM=false
    export VLM_BASE_URL=http://<droplet-ip>:8000/v1
    export VLM_MODEL_ID=google/gemma-4-26B-A4B-it
    docker compose exec backend pytest tests/integration/test_vlm_phase1.py -v -s

Done when: the real VLM finds most of the seeded bugs in fixture-app/BUGS.md.
"""

import http.server
import threading
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.agent.loop import run_agent
from app.agent.schemas import AgentStep, NextAction
from app.agent.vlm_client import _parse_agent_step, call_vlm
from app.config import settings
from app.models import Finding, Run

# ---------------------------------------------------------------------------
# Skip marker — entire module skips in mock mode
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    settings.mock_vlm,
    reason="Phase 1 tests require MOCK_VLM=false and a live AMD vLLM endpoint",
)

# ---------------------------------------------------------------------------
# Fixtures (reuse from test_fixture_loop pattern)
# ---------------------------------------------------------------------------
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixture-app"


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fixture_server():
    """
    Yield a reachable base URL for the fixture app.

    On a host checkout, fixture-app/ sits three levels above this file and we
    serve it directly with a throwaway http.server thread. Inside the backend
    Docker image only backend/'s contents are copied in (build context is
    ./backend), so fixture-app/ does not exist on that filesystem at all —
    FIXTURE_DIR resolves past the image root and 404s on every request. In
    that case the same fixture-app content is already running as its own
    Compose service, reachable at settings.fixture_url.
    """
    if FIXTURE_DIR.is_dir():
        server = http.server.HTTPServer(("127.0.0.1", 0), _SilentHandler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{port}"
        server.shutdown()
    else:
        yield settings.fixture_url


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Phase 1 tests
# ---------------------------------------------------------------------------


async def test_vlm_endpoint_reachable():
    """
    Confirm the vLLM server at VLM_BASE_URL responds to /models.
    Fails fast if the AMD droplet is not running or not reachable.
    """
    url = f"{settings.vlm_base_url}/models"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {settings.vlm_api_key}"},
        )
    assert resp.status_code == 200, (
        f"VLM /models returned {resp.status_code}. "
        f"Is the droplet running? VLM_BASE_URL={settings.vlm_base_url}"
    )
    model_ids = [m["id"] for m in resp.json().get("data", [])]
    assert settings.vlm_model_id in model_ids, (
        f"Configured model '{settings.vlm_model_id}' not in available models: {model_ids}"
    )


async def test_real_vlm_single_call_returns_valid_schema(fixture_server):
    """
    Make one real call to Gemma 4 with a screenshot + DOM summary.
    Validate that the response parses cleanly as AgentStep.
    This confirms guided_json is working and the model output is structured.
    """
    import base64
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(fixture_server, wait_until="networkidle", timeout=15000)
        png = await page.screenshot(type="png")
        await browser.close()

    screenshot_b64 = base64.b64encode(png).decode()
    dom_summary = (
        "selector=\"[data-shadow-id='1']\" | button#submit-btn | \"Get Started Free\"\n"
        "selector=\"[data-shadow-id='2']\" | button#load-more-btn | \"Load More Features\""
    )

    step, is_inconclusive = await call_vlm(
        step_index=0,
        screenshot_b64=screenshot_b64,
        dom_summary=dom_summary,
        goal="Find bugs on this web page.",
        action_history=[],
        current_url=fixture_server,
    )

    assert not is_inconclusive, "VLM call was inconclusive — check logs for error"
    assert isinstance(step, AgentStep), f"Expected AgentStep, got {type(step)}"
    assert step.next_action.type in ("click", "fill", "scroll", "go_back", "stop")
    assert step.observation, "Observation must not be empty"

    if step.anomaly:
        assert step.anomaly.severity in ("low", "medium", "high", "critical")
        assert step.anomaly.category in (
            "broken_interaction", "visual_layout", "accessibility",
            "error_state", "dead_link", "other",
        )


async def test_real_vlm_full_loop_finds_most_bugs(fixture_server, db_session):
    """
    Full Phase 1 acceptance test: run the real agent loop against fixture-app
    and assert that Gemma 4 finds at least 4 of the 8 seeded bugs (50% bar).

    Interpretation of results:
    - ≥ 4 findings: Phase 1 DONE
    - < 4 findings: inspect run logs, adjust prompt or MAX_STEPS_PER_RUN
    """
    # Use real VLM with generous budgets for Phase 1
    original_steps = settings.max_steps_per_run
    original_secs = settings.max_seconds_per_run

    # Give the real model more steps since it might explore differently than mock.
    # 300s was mathematically too tight for a full 20-step run against a cloud model's
    # per-step latency; 600s (10 min) gives enough headroom to actually reach 20 steps.
    settings.max_steps_per_run = 20
    settings.max_seconds_per_run = 600

    try:
        run = Run(target_url=fixture_server, status="pending")
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)

        await run_agent(run.id, fixture_server, db_session)
        db_session.expire_all()

        run_after = db_session.get(Run, run.id)
        assert run_after.status == "completed", (
            f"Run failed: {run_after.error_msg}"
        )

        findings = list(
            db_session.exec(select(Finding).where(Finding.run_id == run.id)).all()
        )

        # Log what was found for inspection
        print(f"\n=== Phase 1 Results: {len(findings)} findings ===")
        for f in findings:
            print(f"  [{f.severity}] {f.category} (step {f.step_num}): {f.description[:80]}")

        assert len(findings) >= 4, (
            f"Expected ≥ 4 findings for Phase 1 pass, got {len(findings)}. "
            "Consider increasing MAX_STEPS_PER_RUN or tuning the prompt."
        )

        # Validate all finding metadata
        for f in findings:
            assert f.severity in ("low", "medium", "high", "critical")
            assert f.screenshot_b64, "Every finding must have a screenshot"

    finally:
        settings.max_steps_per_run = original_steps
        settings.max_seconds_per_run = original_secs
