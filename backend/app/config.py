"""
Application settings loaded from environment variables / .env file.
Everything model/endpoint-related is an env var — nothing is hardcoded.

Both the VLM (vision/decision) and the reporting (Fireworks) clients route
through the same local OpenAI-compatible gateway, configured via
OPENAI_BASE_URL / OPENAI_API_KEY.  Swap the gateway by changing those two
env vars — no code changes needed.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---------- Unified OpenAI-compatible gateway ----------
    # Both the VLM client and the Fireworks reporting client hit this gateway.
    # Set OPENAI_BASE_URL / OPENAI_API_KEY in .env (or the environment) to
    # redirect traffic to any compatible proxy, LiteLLM instance, etc.
    openai_base_url: str = "http://localhost:8000/v1"
    openai_api_key: str = "my_secure_local_password"

    # ---------- VLM / Vision-Decision layer (NEVER Fireworks) ----------
    mock_vlm: bool = True
    vlm_model_id: str = "gemma-4"

    # ---------- Fireworks AI (report-writing step ONLY) ----------
    fireworks_model_id: str = "llama-3.3-70b-versatile"

    # ---------- Agent budget ----------
    max_steps_per_run: int = 20
    max_seconds_per_run: int = 240

    # ---------- Database ----------
    database_url: str = "sqlite:///./shadowqa.db"

    # ---------- Internal ----------
    fixture_url: str = "http://fixture-app:80"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
