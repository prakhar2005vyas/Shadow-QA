"""
Unit tests for the bug report compiler.

compile_findings() must call fireworks_client.generate_report_text() with the
right fields and persist whatever it returns as Report.raw_text. The Fireworks
client itself is mocked here — no real network call is made, and no
FIREWORKS_API_KEY is required, per the "never call real endpoints from unit
tests" rule. fireworks_client's own zero-key stub-fallback behaviour is covered
separately; this file only tests the compiler's wiring to it.
"""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Finding, Report, Run
from app.reporting import compiler


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


def _make_finding(db_session: Session, **overrides) -> Finding:
    run = Run(target_url="http://example.test", status="running")
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    defaults = dict(
        run_id=run.id,
        step_num=3,
        description="Submit button throws a ReferenceError on click.",
        severity="critical",
        category="broken_interaction",
        screenshot_b64="fakebase64",
        console_errors_json='["[ERROR] ReferenceError: handleSubmit is not defined"]',
        network_errors_json="[]",
        action_trail_json='["step 0: click #submit-btn"]',
    )
    defaults.update(overrides)
    finding = Finding(**defaults)
    db_session.add(finding)
    db_session.commit()
    db_session.refresh(finding)
    return finding


async def test_compile_findings_calls_fireworks_with_required_fields(db_session, monkeypatch):
    finding = _make_finding(db_session)

    mock_generate = AsyncMock(return_value="# Mock Fireworks Report\n\nSome polished markdown.")
    monkeypatch.setattr(compiler, "generate_report_text", mock_generate)

    await compiler.compile_findings(finding.run_id, db_session)

    mock_generate.assert_awaited_once_with(
        bug_description=finding.description,
        severity=finding.severity,
        category=finding.category,
        action_trail=finding.action_trail,
    )


async def test_compile_findings_persists_fireworks_output_as_raw_text(db_session, monkeypatch):
    finding = _make_finding(db_session)

    mock_generate = AsyncMock(return_value="# Mock Fireworks Report\n\nSome polished markdown.")
    monkeypatch.setattr(compiler, "generate_report_text", mock_generate)

    await compiler.compile_findings(finding.run_id, db_session)

    report = db_session.exec(
        select(Report).where(Report.finding_id == finding.id)
    ).first()
    assert report is not None, "compile_findings() must persist a Report"
    assert report.raw_text == "# Mock Fireworks Report\n\nSome polished markdown."
    assert report.title, "title must be populated"
    assert finding.severity.upper() in report.title
    assert report.summary == finding.description
    assert report.repro_steps, "repro_steps must be populated"


async def test_compile_findings_is_idempotent(db_session, monkeypatch):
    finding = _make_finding(db_session)

    mock_generate = AsyncMock(return_value="first report")
    monkeypatch.setattr(compiler, "generate_report_text", mock_generate)

    await compiler.compile_findings(finding.run_id, db_session)
    await compiler.compile_findings(finding.run_id, db_session)

    reports = db_session.exec(
        select(Report).where(Report.finding_id == finding.id)
    ).all()
    assert len(reports) == 1, "a second compile pass must not duplicate the report"
    mock_generate.assert_awaited_once()


async def test_compile_findings_marks_inconclusive_on_fireworks_failure(db_session, monkeypatch):
    finding = _make_finding(db_session)

    mock_generate = AsyncMock(side_effect=RuntimeError("Fireworks unreachable"))
    monkeypatch.setattr(compiler, "generate_report_text", mock_generate)

    await compiler.compile_findings(finding.run_id, db_session)

    report = db_session.exec(
        select(Report).where(Report.finding_id == finding.id)
    ).first()
    assert report is not None, "a failed Fireworks call must still produce a Report row"
    assert "inconclusive" in report.raw_text.lower()
