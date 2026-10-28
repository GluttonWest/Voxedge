"""Pydantic schemas for activity / interaction history."""

from datetime import datetime

from pydantic import BaseModel


class InteractionSummary(BaseModel):
    """Compact view of an interaction for the activity feed."""

    id: int
    session_id: str
    recognized_text: str | None
    intent: str | None
    decision_outcome: str | None
    decision_reason: str | None
    target_device_id: str | None
    requested_action: str | None
    execution_status: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityEntry(BaseModel):
    """A device state-change log entry."""

    id: int
    interaction_id: int | None
    device_id: str
    action: str
    previous_state: str
    new_state: str
    success: bool
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityResponse(BaseModel):
    """Combined activity feed."""

    interactions: list[InteractionSummary]
    device_actions: list[ActivityEntry]
    total_interactions: int
    total_actions: int
