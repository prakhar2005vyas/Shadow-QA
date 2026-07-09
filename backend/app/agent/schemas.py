"""
Pydantic schemas for the VLM structured output.
These schemas are used for:
  - Parsing responses from the real vLLM endpoint (via guided_json / structured decoding)
  - Validating mock VLM output
  - Storing findings in the database

Matches the spec exactly:
  NextAction, Anomaly, AgentStep
"""

from typing import Literal, Optional
from pydantic import BaseModel


class NextAction(BaseModel):
    """What the agent will do next."""

    type: Literal["click", "fill", "scroll", "go_back", "stop"]
    selector: Optional[str] = None   # CSS selector (None for scroll/go_back/stop)
    value: Optional[str] = None      # fill value or scroll distance
    reason: str                       # short explanation for the decision log


class Anomaly(BaseModel):
    """A bug or visual anomaly detected at this step."""

    description: str
    severity: Literal["low", "medium", "high", "critical"]
    category: Literal[
        "broken_interaction",
        "visual_layout",
        "accessibility",
        "error_state",
        "dead_link",
        "other",
    ]


class AgentStep(BaseModel):
    """Complete output from a single VLM call."""

    observation: str                  # what the model sees / narration
    anomaly: Optional[Anomaly] = None # None if nothing wrong was found
    next_action: NextAction
