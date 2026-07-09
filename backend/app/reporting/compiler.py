"""
Bug report compiler.

Calls fireworks_client.generate_report_text() to turn each Finding into a polished,
human-readable markdown report. This is the ONLY place in the reporting layer that
talks to Fireworks; vlm_client.py calls AMD vLLM and the two are NEVER mixed.

fireworks_client itself returns a stub report when FIREWORKS_API_KEY is unset, so
this module has no local markdown-assembly fallback of its own — that behaviour
belongs to fireworks_client, not here.
"""

import logging
from sqlmodel import Session, select

from ..models import Finding, Report
from .fireworks_client import generate_report_text

logger = logging.getLogger(__name__)


async def compile_findings(run_id: int, db_session: Session) -> None:
    """
    For every Finding in this run that doesn't yet have a Report, generate one via
    Fireworks AI. If the Fireworks call fails after its built-in retries, the report
    is marked inconclusive rather than crashing the run — consistent with how VLM
    call failures are handled in the agent loop.
    """
    statement = select(Finding).where(Finding.run_id == run_id)
    findings = db_session.exec(statement).all()

    for finding in findings:
        # Skip if report already exists (idempotent)
        existing = db_session.exec(
            select(Report).where(Report.finding_id == finding.id)
        ).first()
        if existing:
            continue

        title = _make_title(finding.category, finding.severity)
        summary = finding.description
        repro_steps = _make_repro_steps(finding)

        try:
            raw_text = await generate_report_text(
                bug_description=finding.description,
                severity=finding.severity,
                category=finding.category,
                action_trail=finding.action_trail,
            )
        except Exception as exc:
            logger.error(
                "Fireworks report generation failed for finding %d after retries: %s",
                finding.id,
                exc,
            )
            raw_text = (
                f"_(Report generation inconclusive — Fireworks call failed after "
                f"retries: {exc})_"
            )

        report = Report(
            finding_id=finding.id,
            title=title,
            summary=summary,
            repro_steps=repro_steps,
            raw_text=raw_text,
        )
        db_session.add(report)
        logger.info("Report compiled for finding %d: %s", finding.id, title)

    db_session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CAT_LABELS: dict[str, str] = {
    "broken_interaction": "Broken Interaction",
    "visual_layout": "Visual Layout Bug",
    "accessibility": "Accessibility Issue",
    "error_state": "Error State",
    "dead_link": "Dead Link",
    "other": "Bug",
}


def _make_title(category: str, severity: str) -> str:
    label = _CAT_LABELS.get(category, "Bug")
    return f"[{severity.upper()}] {label}"


def _make_repro_steps(finding: Finding) -> str:
    lines: list[str] = []

    trail = finding.action_trail
    if trail:
        lines.append("**Actions leading up to this finding:**")
        for action in trail[-5:]:
            lines.append(f"- {action}")
        lines.append("")

    lines.append(f"**Bug first observed at step {finding.step_num}.**")

    console = finding.console_errors
    if console:
        lines.append("")
        lines.append("**Console errors at time of discovery:**")
        for err in console[:5]:
            lines.append(f"- `{err}`")

    network = finding.network_errors
    if network:
        lines.append("")
        lines.append("**Network errors at time of discovery:**")
        for err in network[:5]:
            lines.append(f"- `{err}`")

    return "\n".join(lines)
