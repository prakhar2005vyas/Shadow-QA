"""
Unit tests for VLM output schemas (NextAction, Anomaly, AgentStep).

These tests verify that:
  - Valid data parses correctly
  - Invalid enum values are rejected
  - JSON string parsing works (as returned by vLLM)
  - The mock VLM returns valid AgentStep instances
"""

import pytest
from pydantic import ValidationError

from app.agent.schemas import AgentStep, Anomaly, NextAction
from app.agent.mock_vlm import get_mock_step


# ---------------------------------------------------------------------------
# NextAction
# ---------------------------------------------------------------------------


class TestNextAction:
    def test_click_with_selector(self):
        action = NextAction(type="click", selector="#btn", value=None, reason="test")
        assert action.type == "click"
        assert action.selector == "#btn"

    def test_scroll_with_value(self):
        action = NextAction(type="scroll", selector=None, value="300", reason="scroll down")
        assert action.value == "300"

    def test_stop_minimal(self):
        action = NextAction(type="stop", reason="done")
        assert action.type == "stop"
        assert action.selector is None

    def test_invalid_action_type(self):
        with pytest.raises(ValidationError):
            NextAction(type="fly", reason="??")

    def test_missing_reason_raises(self):
        with pytest.raises(ValidationError):
            NextAction(type="click", selector="#x")


# ---------------------------------------------------------------------------
# Anomaly
# ---------------------------------------------------------------------------


class TestAnomaly:
    def test_valid_anomaly(self):
        a = Anomaly(
            description="Button broken",
            severity="high",
            category="broken_interaction",
        )
        assert a.severity == "high"

    def test_all_valid_severities(self):
        for sev in ("low", "medium", "high", "critical"):
            a = Anomaly(description="x", severity=sev, category="other")
            assert a.severity == sev

    def test_all_valid_categories(self):
        cats = [
            "broken_interaction",
            "visual_layout",
            "accessibility",
            "error_state",
            "dead_link",
            "other",
        ]
        for cat in cats:
            a = Anomaly(description="x", severity="low", category=cat)
            assert a.category == cat

    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            Anomaly(description="x", severity="extreme", category="other")

    def test_invalid_category_raises(self):
        with pytest.raises(ValidationError):
            Anomaly(description="x", severity="high", category="unknown_bug_type")


# ---------------------------------------------------------------------------
# AgentStep
# ---------------------------------------------------------------------------


class TestAgentStep:
    def test_valid_step_no_anomaly(self):
        step = AgentStep(
            observation="Page loaded",
            anomaly=None,
            next_action=NextAction(type="scroll", value="500", reason="explore"),
        )
        assert step.anomaly is None
        assert step.next_action.type == "scroll"

    def test_valid_step_with_anomaly(self):
        step = AgentStep(
            observation="Broken button found",
            anomaly=Anomaly(
                description="Button does nothing",
                severity="critical",
                category="broken_interaction",
            ),
            next_action=NextAction(type="stop", reason="done"),
        )
        assert step.anomaly.severity == "critical"

    def test_parse_from_json_string(self):
        json_str = (
            '{"observation":"test page","anomaly":null,'
            '"next_action":{"type":"scroll","selector":null,"value":"200","reason":"scroll"}}'
        )
        step = AgentStep.model_validate_json(json_str)
        assert step.observation == "test page"
        assert step.next_action.value == "200"

    def test_parse_from_json_with_anomaly(self):
        json_str = (
            '{"observation":"found bug",'
            '"anomaly":{"description":"broken","severity":"high","category":"dead_link"},'
            '"next_action":{"type":"go_back","selector":null,"value":null,"reason":"back"}}'
        )
        step = AgentStep.model_validate_json(json_str)
        assert step.anomaly.category == "dead_link"
        assert step.next_action.type == "go_back"

    def test_invalid_step_bad_action_type_raises(self):
        with pytest.raises(ValidationError):
            AgentStep.model_validate(
                {
                    "observation": "x",
                    "anomaly": None,
                    "next_action": {"type": "teleport", "reason": "??"},
                }
            )


# ---------------------------------------------------------------------------
# Mock VLM
# ---------------------------------------------------------------------------


class TestMockVlm:
    def test_step_0_returns_agent_step(self):
        step = get_mock_step(0, "http://fixture-app", "button#submit")
        assert isinstance(step, AgentStep)

    def test_step_0_has_anomaly(self):
        step = get_mock_step(0, "http://fixture-app", "")
        assert step.anomaly is not None
        assert step.anomaly.category == "visual_layout"

    def test_step_1_has_anomaly(self):
        step = get_mock_step(1, "http://fixture-app", "")
        assert step.anomaly is not None
        assert step.anomaly.category == "accessibility"

    def test_step_2_is_critical(self):
        step = get_mock_step(2, "http://fixture-app", "")
        assert step.anomaly is not None
        assert step.anomaly.severity == "critical"

    def test_final_step_stops(self):
        step = get_mock_step(6, "http://fixture-app", "")
        assert step.next_action.type == "stop"

    def test_beyond_script_stops(self):
        step = get_mock_step(999, "http://fixture-app", "")
        assert step.next_action.type == "stop"
        assert step.anomaly is None

    def test_all_mock_steps_produce_valid_schemas(self):
        """Every scripted step must produce a fully-valid AgentStep."""
        for i in range(7):  # 0..6 — 7 steps total (step 5 = broken image, step 6 = label mismatch)
            step = get_mock_step(i, "http://fixture-app", "dom summary")
            assert isinstance(step, AgentStep)
            assert step.next_action.type in ("click", "fill", "scroll", "go_back", "stop")
            if step.anomaly:
                assert step.anomaly.severity in ("low", "medium", "high", "critical")
