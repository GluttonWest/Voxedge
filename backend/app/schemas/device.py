"""Pydantic schemas for device API requests and responses."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── Response schemas ──────────────────────────────────────────────────────────

class DeviceResponse(BaseModel):
    """Public representation of a device."""

    id: str
    name: str
    device_type: str
    location: str
    state: str
    supported_actions: list[str]
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Wrapper for listing multiple devices."""

    devices: list[DeviceResponse]
    count: int


# ── Request schemas ───────────────────────────────────────────────────────────

class DeviceCommandRequest(BaseModel):
    """Manual device command from the frontend (bypasses voice but still
    goes through backend validation)."""

    action: str = Field(..., description="Action to perform, e.g. 'ON' or 'OFF'")


class DeviceStateUpdate(BaseModel):
    """Response after a device command is processed."""

    device_id: str
    action: str
    previous_state: str
    new_state: str
    success: bool
    message: str
