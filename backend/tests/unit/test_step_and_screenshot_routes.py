"""
Unit tests for the step feed and screenshot routes:
  GET /runs/{id}/steps
  GET /runs/{id}/steps/{step_num}/screenshot
  GET /runs/{id}/findings/{finding_id}/screenshot

Uses a dependency-overridden in-memory SQLite session so these tests don't touch
the real database file and are fully isolated/repeatable.
"""

import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import Finding, Run, Step

# A tiny 1x1 red PNG, base64-encoded — used as fake screenshot data.
_FAKE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YA"
    "AAAASUVORK5CYII="
)


@pytest.fixture
def seeded_client():
    """TestClient wired to a fresh in-memory DB, pre-seeded with a run/steps/finding."""
    # StaticPool keeps a single shared connection alive across threads — FastAPI
    # dispatches sync route handlers to a worker thread pool, and a plain
    # sqlite:///:memory: engine would otherwise hand each thread its own private,
    # empty in-memory database.
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

    with Session(engine) as session:
        run = Run(target_url="http://example.test", status="running")
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(
            Step(
                run_id=run.id,
                step_num=0,
                observation="Page loaded.",
                is_anomaly=False,
                action_type="scroll",
                action_selector=None,
                action_reason="explore the page",
            )
        )
        session.add(
            Step(
                run_id=run.id,
                step_num=1,
                observation="Found a broken image in the hero section.",
                is_anomaly=True,
                action_type="click",
                action_selector="[data-shadow-id='1']",
                action_reason="test the privacy link",
                screenshot_b64=_FAKE_PNG_B64,
            )
        )

        finding = Finding(
            run_id=run.id,
            step_num=1,
            description="Broken image in the hero section",
            severity="low",
            category="visual_layout",
            screenshot_b64=_FAKE_PNG_B64,
        )
        session.add(finding)
        session.commit()
        session.refresh(finding)

        run_id, finding_id = run.id, finding.id

    with TestClient(app) as client:
        yield client, run_id, finding_id

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /runs/{id}/steps
# ---------------------------------------------------------------------------


def test_get_steps_returns_ordered_steps(seeded_client):
    client, run_id, _ = seeded_client
    resp = client.get(f"/runs/{run_id}/steps")
    assert resp.status_code == 200
    steps = resp.json()
    assert len(steps) == 2
    assert [s["step_num"] for s in steps] == [0, 1]
    assert steps[0]["has_screenshot"] is False
    assert steps[1]["has_screenshot"] is True
    assert steps[1]["is_anomaly"] is True
    assert steps[1]["action_selector"] == "[data-shadow-id='1']"


def test_get_steps_404_for_unknown_run(seeded_client):
    client, _, _ = seeded_client
    resp = client.get("/runs/999999/steps")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{id}/steps/{step_num}/screenshot
# ---------------------------------------------------------------------------


def test_step_screenshot_returns_png_bytes(seeded_client):
    client, run_id, _ = seeded_client
    resp = client.get(f"/runs/{run_id}/steps/1/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == base64.b64decode(_FAKE_PNG_B64)


def test_step_screenshot_404_when_missing(seeded_client):
    client, run_id, _ = seeded_client
    resp = client.get(f"/runs/{run_id}/steps/0/screenshot")
    assert resp.status_code == 404


def test_step_screenshot_404_unknown_step_num(seeded_client):
    client, run_id, _ = seeded_client
    resp = client.get(f"/runs/{run_id}/steps/999/screenshot")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{id}/findings/{finding_id}/screenshot
# ---------------------------------------------------------------------------


def test_finding_screenshot_returns_png_bytes(seeded_client):
    client, run_id, finding_id = seeded_client
    resp = client.get(f"/runs/{run_id}/findings/{finding_id}/screenshot")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == base64.b64decode(_FAKE_PNG_B64)


def test_finding_screenshot_404_for_wrong_run(seeded_client):
    client, _, finding_id = seeded_client
    resp = client.get(f"/runs/999999/findings/{finding_id}/screenshot")
    assert resp.status_code == 404


def test_finding_screenshot_404_when_missing(seeded_client):
    client, run_id, _ = seeded_client
    resp = client.get(f"/runs/{run_id}/findings/999999/screenshot")
    assert resp.status_code == 404
