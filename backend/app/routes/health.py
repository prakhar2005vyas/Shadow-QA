"""
Health check endpoint.
"""

from fastapi import APIRouter

from ..config import settings

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """
    Returns service health status and current mode.
    This is what the smoke-test script checks after docker compose up.
    """
    return {
        "status": "ok",
        "mock_vlm": settings.mock_vlm,
        "vlm_model_id": settings.vlm_model_id,
        "fireworks_model_id": settings.fireworks_model_id,
    }
