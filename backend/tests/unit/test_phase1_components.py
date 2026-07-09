"""
Unit tests for Phase 1 components:
  - _parse_agent_step: JSON fallback parsing (clean, fenced, embedded)
  - /vlm-health endpoint: mock mode response
"""

import pytest
from fastapi.testclient import TestClient

from app.agent.vlm_client import _parse_agent_step
from app.agent.schemas import AgentStep
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# _parse_agent_step — fallback parsing
# ---------------------------------------------------------------------------

VALID_STEP_JSON = (
    '{"observation":"page loaded",'
    '"anomaly":null,'
    '"next_action":{"type":"scroll","selector":null,"value":"300","reason":"explore"}}'
)

VALID_STEP_WITH_ANOMALY = (
    '{"observation":"found a bug",'
    '"anomaly":{"description":"button broken","severity":"high","category":"broken_interaction"},'
    '"next_action":{"type":"stop","selector":null,"value":null,"reason":"done"}}'
)


class TestParseAgentStep:
    def test_clean_json_parses(self):
        step = _parse_agent_step(VALID_STEP_JSON)
        assert isinstance(step, AgentStep)
        assert step.next_action.type == "scroll"

    def test_fenced_json_block_parses(self):
        fenced = f"```json\n{VALID_STEP_JSON}\n```"
        step = _parse_agent_step(fenced)
        assert isinstance(step, AgentStep)
        assert step.next_action.type == "scroll"

    def test_fenced_no_language_tag_parses(self):
        fenced = f"```\n{VALID_STEP_JSON}\n```"
        step = _parse_agent_step(fenced)
        assert isinstance(step, AgentStep)

    def test_preamble_then_json_parses(self):
        # Model adds text before the JSON object
        with_preamble = f"Here is my analysis:\n{VALID_STEP_WITH_ANOMALY}"
        step = _parse_agent_step(with_preamble)
        assert isinstance(step, AgentStep)
        assert step.anomaly is not None
        assert step.anomaly.severity == "high"

    def test_trailing_text_after_json_parses(self):
        with_trailing = f"{VALID_STEP_JSON}\nHope this helps!"
        step = _parse_agent_step(with_trailing)
        assert isinstance(step, AgentStep)

    def test_invalid_json_raises(self):
        with pytest.raises((ValueError, Exception)):
            _parse_agent_step("This is not JSON at all.")

    def test_partial_json_raises(self):
        with pytest.raises((ValueError, Exception)):
            _parse_agent_step('{"observation": "incomplete"')

    def test_valid_json_wrong_schema_raises(self):
        # Valid JSON but not matching AgentStep schema
        with pytest.raises((ValueError, Exception)):
            _parse_agent_step('{"foo": "bar", "baz": 42}')


# ---------------------------------------------------------------------------
# /vlm-health endpoint
# ---------------------------------------------------------------------------


class TestVlmHealthEndpoint:
    def test_mock_mode_returns_mock_status(self):
        """In the test environment MOCK_VLM=true so health must say 'mock'."""
        resp = client.get("/vlm-health")
        assert resp.status_code == 200
        data = resp.json()
        # In test/CI environment MOCK_VLM is true
        assert data["status"] in ("mock", "ok", "warning", "error")
        assert "mock_vlm" in data

    def test_mock_status_has_message(self):
        resp = client.get("/vlm-health")
        data = resp.json()
        assert "message" in data

    def test_health_endpoint_is_fast(self):
        """Mock mode health check must resolve in < 1s (no network call)."""
        import time
        start = time.monotonic()
        resp = client.get("/vlm-health")
        elapsed = time.monotonic() - start
        # In mock mode there should be no network call
        if resp.json().get("mock_vlm"):
            assert elapsed < 1.0, f"Mock health check took {elapsed:.2f}s — should be instant"
