"""Pydantic schemas for decision confirmation / clarification responses."""

from pydantic import BaseModel, Field


class ConfirmationRequest(BaseModel):
    """User's response to a clarification or confirmation prompt."""

    session_id: str = Field(..., description="Session ID of the pending interaction")
    response: str = Field(
        ...,
        description=(
            "User's clarification answer, e.g. 'the bedroom light', 'yes', 'no', 'cancel'"
        ),
    )
    interaction_id: int | None = Field(
        default=None,
        description="ID of the interaction being responded to",
    )


class ConfirmationResponse(BaseModel):
    """Result of processing a confirmation / clarification."""

    interaction_id: int
    session_id: str
    decision: str
    decision_reason: str
    target_device: str | None = None
    requested_action: str | None = None
    execution_status: str | None = None
    new_device_state: str | None = None
    message: str
    clarification_question: str | None = None
