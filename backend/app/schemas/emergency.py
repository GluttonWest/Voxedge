"""Pydantic schemas for emergency workflow."""

from datetime import datetime

from pydantic import BaseModel, Field


class EmergencyContact(BaseModel):
    """A simulated emergency contact."""

    name: str
    relationship: str
    phone: str
    notified: bool = False
    notified_at: datetime | None = None


class EmergencyTriggerRequest(BaseModel):
    """Request to trigger the emergency workflow."""

    trigger_text: str = Field(
        default="Emergency assistance requested",
        description="What triggered the emergency (voice text or manual button)",
    )
    severity: str = Field(
        default="HIGH",
        description="Severity level: LOW, MEDIUM, HIGH, CRITICAL",
    )


class EmergencyEventResponse(BaseModel):
    """Public representation of an emergency event."""

    id: int
    trigger_text: str
    status: str
    severity: str
    contacts: list[EmergencyContact]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class EmergencyUpdateRequest(BaseModel):
    """Request to update an emergency event status."""

    status: str = Field(
        ..., description="New status: ACKNOWLEDGED, CANCELLED, COMPLETED"
    )
    notes: str | None = None
