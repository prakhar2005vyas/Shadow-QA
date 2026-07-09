"""
SQLModel database models: Run, Finding, Report.
"""

import json
from datetime import datetime
from typing import Optional, List

from sqlmodel import SQLModel, Field, Relationship


class Run(SQLModel, table=True):
    """A single agent run against a target URL."""

    id: Optional[int] = Field(default=None, primary_key=True)
    target_url: str
    status: str = Field(default="pending")  # pending | running | completed | failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    total_steps: int = Field(default=0)

    findings: List["Finding"] = Relationship(back_populates="run")


class Finding(SQLModel, table=True):
    """A single bug / anomaly detected during a run."""

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="run.id", index=True)
    step_num: int
    description: str
    severity: str   # low | medium | high | critical
    category: str   # broken_interaction | visual_layout | accessibility | error_state | dead_link | other

    # Screenshot stored as base64-encoded PNG
    screenshot_b64: Optional[str] = Field(default=None)

    # JSON arrays serialised as text (SQLite has no native JSON column)
    console_errors_json: str = Field(default="[]")
    network_errors_json: str = Field(default="[]")
    action_trail_json: str = Field(default="[]")

    run: Optional[Run] = Relationship(back_populates="findings")
    report: Optional["Report"] = Relationship(back_populates="finding")

    # --- convenience properties ---
    @property
    def console_errors(self) -> list[str]:
        return json.loads(self.console_errors_json)

    @property
    def network_errors(self) -> list[str]:
        return json.loads(self.network_errors_json)

    @property
    def action_trail(self) -> list[str]:
        return json.loads(self.action_trail_json)


class Report(SQLModel, table=True):
    """A structured bug report compiled from a Finding."""

    id: Optional[int] = Field(default=None, primary_key=True)
    finding_id: int = Field(foreign_key="finding.id", unique=True)
    title: str
    summary: str
    repro_steps: str
    raw_text: str  # full markdown report

    finding: Optional[Finding] = Relationship(back_populates="report")
