"""
VLM health-check endpoint.

GET /vlm-health — verifies connectivity to the configured vLLM endpoint
(or reports mock mode immediately). Use this before starting a run to
confirm the AMD droplet is reachable and the model is loaded.
"""

import logging

import httpx
from fastapi import APIRouter

from ..config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/vlm-health")
async def vlm_health() -> dict:
    """
    Check VLM endpoint connectivity.
    In mock mode returns immediately without a network call.
    In real mode hits /models on the vLLM server and returns model info.
    """
    if settings.mock_vlm:
        return {
            "status": "mock",
            "mock_vlm": True,
            "message": "MOCK_VLM=true — no real VLM calls are made",
        }

    url = f"{settings.vlm_base_url}/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {settings.vlm_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            model_ids = [m["id"] for m in data.get("data", [])]
            configured_loaded = settings.vlm_model_id in model_ids
            return {
                "status": "ok" if configured_loaded else "warning",
                "mock_vlm": False,
                "vlm_base_url": settings.vlm_base_url,
                "configured_model": settings.vlm_model_id,
                "models_available": model_ids,
                "configured_model_loaded": configured_loaded,
                "message": (
                    "VLM endpoint reachable and configured model is loaded"
                    if configured_loaded
                    else f"VLM reachable but '{settings.vlm_model_id}' not in available models"
                ),
            }
    except httpx.ConnectError as exc:
        logger.error("VLM health check failed (connection error): %s", exc)
        return {
            "status": "error",
            "mock_vlm": False,
            "vlm_base_url": settings.vlm_base_url,
            "error": f"Connection refused or DNS failure: {exc}",
            "message": "Cannot reach VLM endpoint. Is the AMD droplet running?",
        }
    except Exception as exc:
        logger.error("VLM health check failed: %s", exc)
        return {
            "status": "error",
            "mock_vlm": False,
            "vlm_base_url": settings.vlm_base_url,
            "error": str(exc),
        }
