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
    auth_secret_key: str = "voxedge-secure-speaker-auth-secret-key-2026"

    def get_enrolled_voice_path(self) -> Path:
        """Resolve the enrolled voice path relative to current dir or parent."""
        p = Path(self.enrolled_voice_path)
        if p.is_absolute():
            return p
        if p.exists():
            return p.resolve()
        # If it matches the default relative path, check standard locations
        if self.enrolled_voice_path in ("../enrolled_voice.npy", "enrolled_voice.npy"):
            p_cwd = Path("enrolled_voice.npy")
            if p_cwd.exists():
                return p_cwd.resolve()
            p_parent = Path("../enrolled_voice.npy")
            if p_parent.exists():
                return p_parent.resolve()
            if Path.cwd().name == "backend":
                return p_parent.resolve()
            return p_cwd.resolve()
        return p.resolve()

    def get_vosk_model_path(self) -> Path:
        """Resolve the Vosk model directory."""
        p = Path(self.vosk_model_path)
        if p.is_dir():
            return p.resolve()
        p_cwd = Path("model")
        if p_cwd.is_dir():
            return p_cwd.resolve()
        p_parent = Path("../model")
        if p_parent.is_dir():
            return p_parent.resolve()
        return p.resolve()

    # ── Decision engine & Context ──────────────────────────────────────────
    intent_confidence_threshold: float = 0.6
    context_expiry_seconds: int = 120
    max_clarification_attempts: int = 2
    max_conversation_history: int = 50  # Retention limit for interactions

    # ── Small Language Model (SLM) Integration ─────────────────────────────
    slm_enabled: bool = True
    slm_provider: str = "local"  # "local", "ollama", "mock"
    slm_model_name: str = "qwen2.5-0.5b"
    slm_api_base: str = "http://localhost:11434"
    slm_timeout_seconds: float = 3.0
    slm_confidence_threshold: float = 0.65

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
