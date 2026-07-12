"""
Integration test — run_agent's handling of a completely unreachable target.

Exercises the real BrowserSession/Playwright navigate() call against a closed
local port (connection refused), asserting the loop records a single critical
'error_state' finding and concludes the run as 'completed' — rather than
crashing with an unhandled navigation exception or exploring a browser error
page as if it were real content.
"""

from sqlmodel import Session, SQLModel, create_engine, select

from app.agent.loop import run_agent
from app.config import settings
from app.models import Finding, Run, Step

# Port 9 (the "discard" service) is not listened on in CI/dev environments —
# same convention already used by test_fixture_loop.py's "run not found" test.
_UNREACHABLE_URL = "http://127.0.0.1:9"


async def test_run_agent_records_critical_finding_on_unreachable_target(monkeypatch):
    monkeypatch.setattr(settings, "mock_vlm", True)
    monkeypatch.setattr(settings, "max_steps_per_run", 10)
    monkeypatch.setattr(settings, "max_seconds_per_run", 120)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db_session:
        run = Run(target_url=_UNREACHABLE_URL, status="pending")
        db_session.add(run)
        db_session.commit()
        db_session.refresh(run)

        await run_agent(run.id, _UNREACHABLE_URL, db_session)

        db_session.expire_all()
        run_after = db_session.get(Run, run.id)

        # Concludes gracefully — not "failed" (that's reserved for unhandled
        # exceptions), and not left "running" forever.
        assert run_after.status == "completed"
        assert run_after.total_steps == 1

        findings = list(db_session.exec(select(Finding).where(Finding.run_id == run.id)).all())
        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert findings[0].category == "error_state"
        assert "could not be reached" in findings[0].description.lower()

        steps = list(db_session.exec(select(Step).where(Step.run_id == run.id)).all())
        assert len(steps) == 1
        assert steps[0].is_anomaly is True
