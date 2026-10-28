"""Pydantic schemas for system status endpoint."""

from datetime import datetime

from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    """Overall system health information."""

    status: str  # "healthy", "degraded", "error"
    version: str
    vosk_model_loaded: bool
    voice_enrolled: bool
    total_devices: int
    active_devices: int
    total_interactions: int
    active_emergencies: int
    uptime_seconds: float
    timestamp: datetime
