"""
Integration test — basic backend service connectivity and response structure.

Uses httpx's ASGITransport to call the FastAPI app in-process; no live server
or Docker is required. Validates that:
  - GET /health returns HTTP 200
  - The response body contains all expected fields with correct types/values
  - The service advertises its current operating mode (mock_vlm flag)
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> AsyncClient:
    """Return an httpx AsyncClient wired directly to the FastAPI ASGI app."""
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_health_returns_200():
    """GET /health must respond with HTTP 200 OK."""
    async with _make_client() as client:
        response = await client.get("/health")

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. Body: {response.text}"
    )


async def test_health_response_is_json():
    """Response Content-Type must be application/json."""
    async with _make_client() as client:
        response = await client.get("/health")

    assert "application/json" in response.headers.get("content-type", ""), (
        f"Expected JSON content-type, got: {response.headers.get('content-type')}"
    )


async def test_health_response_structure():
    """
    Response body must contain the four documented fields with correct types.

    Expected schema:
        {
            "status":             str   — always "ok"
            "mock_vlm":           bool
            "vlm_model_id":       str
            "fireworks_model_id": str
        }
    """
    async with _make_client() as client:
        response = await client.get("/health")

    body = response.json()

    # All required keys must be present
    required_keys = {"status", "mock_vlm", "vlm_model_id", "fireworks_model_id"}
    missing = required_keys - body.keys()
    assert not missing, f"Health response missing keys: {missing}. Got: {list(body.keys())}"

    # Type checks
    assert isinstance(body["status"], str), (
        f"'status' must be a string, got {type(body['status'])}"
    )
    assert isinstance(body["mock_vlm"], bool), (
        f"'mock_vlm' must be a bool, got {type(body['mock_vlm'])}"
    )
    assert isinstance(body["vlm_model_id"], str), (
        f"'vlm_model_id' must be a string, got {type(body['vlm_model_id'])}"
    )
    assert isinstance(body["fireworks_model_id"], str), (
        f"'fireworks_model_id' must be a string, got {type(body['fireworks_model_id'])}"
    )


async def test_health_status_value():
    """The 'status' field must be 'ok' when the service is healthy."""
    async with _make_client() as client:
        response = await client.get("/health")

    assert response.json()["status"] == "ok", (
        f"Expected status='ok', got: {response.json()['status']!r}"
    )


async def test_health_model_ids_are_nonempty():
    """Model ID fields must not be empty strings."""
    async with _make_client() as client:
        response = await client.get("/health")

    body = response.json()
    assert body["vlm_model_id"].strip(), "vlm_model_id must not be blank"
    assert body["fireworks_model_id"].strip(), "fireworks_model_id must not be blank"


async def test_health_reflects_mock_vlm_setting(monkeypatch):
    """
    The 'mock_vlm' flag in the response must track the live settings value.
    Monkeypatches settings to True and False in turn and checks the response.
    """
    from app.config import settings

    # Force mock_vlm = True
    monkeypatch.setattr(settings, "mock_vlm", True)
    async with _make_client() as client:
        resp_true = await client.get("/health")
    assert resp_true.json()["mock_vlm"] is True, (
        "Expected mock_vlm=True in response when settings.mock_vlm=True"
    )

    # Force mock_vlm = False
    monkeypatch.setattr(settings, "mock_vlm", False)
    async with _make_client() as client:
        resp_false = await client.get("/health")
    assert resp_false.json()["mock_vlm"] is False, (
        "Expected mock_vlm=False in response when settings.mock_vlm=False"
    )
