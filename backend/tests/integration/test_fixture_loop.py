"""
Integration test — full agent loop against fixture-app.

Runs the entire perception-decision-action loop with MOCK_VLM=true
against a local HTTP server serving the fixture-app static files.
Asserts that the loop completes and finds ≥ 3 bugs from ≥ 2 categories.

No GPU calls, no external API calls, no Docker required to run this test.
The fixture-app is served by Python's built-in http.server on a random port.
"""

import http.server
import threading
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.agent.loop import run_agent
from app.config import settings
from app.models import Finding, Report, Run, Step


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Resolve fixture-app directory:
#   - Local dev: <repo-root>/fixture-app (4 levels up from this file)
#   - Docker:    /fixture-app (mounted or at /fixture-app)
_LOCAL_FIXTURE = Path(__file__).resolve().parents[3] / "fixture-app"
_DOCKER_FIXTURE = Path("/fixture-app")
FIXTURE_DIR = _LOCAL_FIXTURE if _LOCAL_FIXTURE.exists() else _DOCKER_FIXTURE


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    """Serves fixture-app/ without printing logs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # silence during tests


@pytest.fixture(scope="module")
def fixture_server():
    """Start a local HTTP server serving fixture-app/ on a random port."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _SilentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    yield url
    server.shutdown()


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_loop_finds_at_least_three_bugs(fixture_server, db_session, monkeypatch):
    """
    The mock agent loop must produce ≥ 3 findings with valid metadata.
    This is the primary Phase 0 acceptance criterion.
    """
    # Force mock mode and short budgets for test speed
    monkeypatch.setattr(settings, "mock_vlm", True)
    monkeypatch.setattr(settings, "max_steps_per_run", 10)
    monkeypatch.setattr(settings, "max_seconds_per_run", 120)

    # Create run directly — bypass SSRF guard (localhost is fine in tests)
    run = Run(target_url=fixture_server, status="pending")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    await run_agent(run.id, fixture_server, db_session)

    db_session.expire_all()
    run_after = db_session.get(Run, run.id)

    assert run_after.status == "completed", (
        f"Expected run status='completed', got '{run_after.status}'. "
        f"Error: {run_after.error_msg}"
    )

    findings = list(
        db_session.exec(select(Finding).where(Finding.run_id == run.id)).all()
    )

    assert len(findings) >= 3, (
        f"Expected ≥ 3 findings, got {len(findings)}: "
        + str([f.description[:60] for f in findings])
    )

    # All findings must have valid metadata
    valid_severities = {"low", "medium", "high", "critical"}
    valid_categories = {
        "broken_interaction",
        "visual_layout",
        "accessibility",
        "error_state",
        "dead_link",
        "other",
    }
    for f in findings:
        assert f.severity in valid_severities, f"Invalid severity: {f.severity}"
        assert f.category in valid_categories, f"Invalid category: {f.category}"
        assert f.description, "Finding description must not be empty"
        assert f.screenshot_b64, f"Finding {f.id} missing screenshot"

    # Must cover at least 2 different bug categories
    categories = {f.category for f in findings}
    assert len(categories) >= 2, (
        f"Expected findings from ≥ 2 categories, got: {categories}"
    )

    # Every step (not just anomaly ones) must be persisted for the live agent view
    steps = list(
        db_session.exec(select(Step).where(Step.run_id == run.id)).all()
    )
    assert len(steps) == run_after.total_steps, (
        f"Expected {run_after.total_steps} persisted steps, got {len(steps)}"
    )
    assert sum(1 for s in steps if s.is_anomaly) == len(findings), (
        "Step.is_anomaly count must match the number of Findings recorded"
    )
    assert all(s.screenshot_b64 for s in steps), "Every step must have a screenshot"


async def test_loop_generates_reports(fixture_server, db_session, monkeypatch):
    """
    After the loop, every finding should have a compiled Report.
    """
    monkeypatch.setattr(settings, "mock_vlm", True)
    monkeypatch.setattr(settings, "max_steps_per_run", 10)
    monkeypatch.setattr(settings, "max_seconds_per_run", 120)

    run = Run(target_url=fixture_server, status="pending")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    await run_agent(run.id, fixture_server, db_session)
    db_session.expire_all()

    findings = list(
        db_session.exec(select(Finding).where(Finding.run_id == run.id)).all()
    )
    assert findings, "No findings — loop may have failed"

    for finding in findings:
        report = db_session.exec(
            select(Report).where(Report.finding_id == finding.id)
        ).first()
        assert report is not None, f"Finding {finding.id} has no Report"
        assert report.title, "Report title must not be empty"
        assert report.summary, "Report summary must not be empty"
        assert report.raw_text, "Report raw_text must not be empty"


async def test_loop_handles_run_not_found_gracefully(db_session, monkeypatch):
    """
    Calling run_agent with a non-existent run_id must not raise.
    """
    monkeypatch.setattr(settings, "mock_vlm", True)
    # Should return without raising
    await run_agent(run_id=99999, target_url="http://127.0.0.1:9", db_session=db_session)
