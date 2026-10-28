"""Core configuration loaded from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings — values come from .env or OS environment."""

    # ── Database ───────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./voxedge.db"

    # ── Vosk model ─────────────────────────────────────────────────────────
    vosk_model_path: str = "../model"

    # ── Speaker verification ───────────────────────────────────────────────
    similarity_threshold: float = 0.65
    enrolled_voice_path: str = "../enrolled_voice.npy"

    # ── Decision engine ────────────────────────────────────────────────────
    intent_confidence_threshold: float = 0.6
    context_expiry_seconds: int = 120
    max_clarification_attempts: int = 2

    # ── Emergency ──────────────────────────────────────────────────────────
    emergency_auto_timeout_seconds: int = 300

    # ── Server ─────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # ── CORS ───────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton — import this from anywhere
settings = Settings()
