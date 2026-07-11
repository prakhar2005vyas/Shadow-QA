"""
Unit tests for:
  POST /runs/{id}/cancel  — request cancellation of an in-progress run
  DELETE /runs            — clear history (cascade-deletes findings/steps/reports)

Uses a dependency-overridden in-memory SQLite session, same convention as
test_step_and_screenshot_routes.py, so these tests never touch the real DB file.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import Finding, Report, Run, Step


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    yield engine
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_engine):
    with TestClient(app) as c:
        yield c


def _make_run(engine, status: str) -> int:
    with Session(engine) as session:
        run = Run(target_url="http://example.test", status=status)
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# POST /runs/{id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_running_run_sets_status_cancelled(client, db_engine):
    run_id = _make_run(db_engine, "running")
    resp = client.post(f"/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    with Session(db_engine) as session:
        assert session.get(Run, run_id).status == "cancelled"


def test_cancel_pending_run_sets_status_cancelled(client, db_engine):
    run_id = _make_run(db_engine, "pending")
    resp = client.post(f"/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
def test_cancel_is_noop_on_terminal_states(client, db_engine, terminal_status):
    run_id = _make_run(db_engine, terminal_status)
    resp = client.post(f"/runs/{run_id}/cancel")
    assert resp.status_code == 200
    # Status is unchanged — cancelling an already-finished run doesn't relabel it.
    assert resp.json()["status"] == terminal_status


def test_cancel_404_for_unknown_run(client):
    resp = client.post("/runs/999999/cancel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /runs
# ---------------------------------------------------------------------------


def test_clear_history_deletes_all_runs_and_reports_count(client, db_engine):
    _make_run(db_engine, "completed")
    _make_run(db_engine, "failed")

    resp = client.delete("/runs")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}

    with Session(db_engine) as session:
        assert session.exec(select(Run)).all() == []


def test_clear_history_cascades_to_findings_steps_and_reports(client, db_engine):
    with Session(db_engine) as session:
        run = Run(target_url="http://example.test", status="completed")
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(Step(run_id=run.id, step_num=0, observation="ok", action_type="scroll", action_reason="explore"))

        finding = Finding(
            run_id=run.id,
            step_num=0,
            description="broken thing",
            severity="low",
            category="visual_layout",
        )
        session.add(finding)
        session.commit()
        session.refresh(finding)

        session.add(
            Report(
                finding_id=finding.id,
                title="Broken thing",
                summary="A thing is broken.",
                repro_steps="1. Load page",
                raw_text="# Broken thing\n...",
            )
        )
        session.commit()

    resp = client.delete("/runs")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1}

    with Session(db_engine) as session:
        assert session.exec(select(Run)).all() == []
        assert session.exec(select(Step)).all() == []
        assert session.exec(select(Finding)).all() == []
        assert session.exec(select(Report)).all() == []


def test_clear_history_on_empty_db_returns_zero(client):
    resp = client.delete("/runs")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0}
