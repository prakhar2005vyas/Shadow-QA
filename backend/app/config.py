"""
Application settings loaded from environment variables / .env file.
Everything model/endpoint-related is an env var — nothing is hardcoded.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---------- VLM / Vision-Decision layer (AMD vLLM, NEVER Fireworks) ----------
    mock_vlm: bool = True
    vlm_base_url: str = "http://placeholder:8000/v1"
    vlm_model_id: str = "google/gemma-4-26B-A4B-it"
    vlm_api_key: str = "changeme"

    # ---------- Fireworks AI (report-writing step ONLY) ----------
    fireworks_api_key: str = ""
    fireworks_model_id: str = "accounts/fireworks/models/llama-v3p3-70b-instruct"

    # ---------- Agent budget ----------
    max_steps_per_run: int = 20
    max_seconds_per_run: int = 240

    # ---------- Database ----------
    database_url: str = "sqlite:///./shadowqa.db"

    # ---------- Internal ----------
    fixture_url: str = "http://fixture-app:80"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
