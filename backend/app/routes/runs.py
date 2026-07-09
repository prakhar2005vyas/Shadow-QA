"""
Runs API routes.

POST /runs       — create a new run (kicks off agent in background)
GET  /runs       — list all runs
GET  /runs/{id}  — get run details with findings and reports
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Finding, Report, Run
from ..security.url_guard import SSRFError, check_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    target_url: str


class FindingResponse(BaseModel):
    id: int
    step_num: int
    description: str
    severity: str
    category: str
    has_screenshot: bool
    report_title: Optional[str] = None
    report_summary: Optional[str] = None
    report_raw: Optional[str] = None


class RunResponse(BaseModel):
    id: int
    target_url: str
    status: str
    total_steps: int
    findings: list[FindingResponse] = []
    error_msg: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=RunResponse, status_code=201)
async def create_run(
    body: RunCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> RunResponse:
    """
    Create a new agent run.
    The SSRF guard is applied before the run is persisted.
    The agent loop runs in the background — this returns immediately with the run ID.
    """
    # SSRF guard — reject private/loopback targets
    try:
        check_url(body.target_url)
    except SSRFError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run = Run(target_url=body.target_url)
    session.add(run)
    session.commit()
    session.refresh(run)
    logger.info("Run %d created for %s", run.id, body.target_url)

    # Kick off agent loop in background (uses its own DB session)
    background_tasks.add_task(_run_agent_background, run.id, body.target_url)

    return _run_to_response(run, [], session)


@router.get("", response_model=list[RunResponse])
def list_runs(session: Session = Depends(get_session)) -> list[RunResponse]:
    """List all runs with their findings."""
    runs = session.exec(select(Run)).all()
    return [_run_to_response(r, _get_findings(r.id, session), session) for r in runs]


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: int, session: Session = Depends(get_session)) -> RunResponse:
    """Get a specific run with full finding and report details."""
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _run_to_response(run, _get_findings(run_id, session), session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_findings(run_id: int, session: Session) -> list[Finding]:
    return list(session.exec(select(Finding).where(Finding.run_id == run_id)).all())


def _run_to_response(run: Run, findings: list[Finding], session: Session) -> RunResponse:
    finding_responses: list[FindingResponse] = []
    for f in findings:
        report = session.exec(select(Report).where(Report.finding_id == f.id)).first()
        finding_responses.append(
            FindingResponse(
                id=f.id,
                step_num=f.step_num,
                description=f.description,
                severity=f.severity,
                category=f.category,
                has_screenshot=bool(f.screenshot_b64),
                report_title=report.title if report else None,
                report_summary=report.summary if report else None,
                report_raw=report.raw_text if report else None,
            )
        )
    return RunResponse(
        id=run.id,
        target_url=run.target_url,
        status=run.status,
        total_steps=run.total_steps,
        findings=finding_responses,
        error_msg=run.error_msg,
    )


async def _run_agent_background(run_id: int, target_url: str) -> None:
    """Background task wrapper — uses its own DB session."""
    from ..agent.loop import run_agent

    with Session(engine) as session:
        await run_agent(run_id, target_url, session)

