"""Pydantic schemas for voice processing API."""

from pydantic import BaseModel, Field


class VoiceProcessRequest(BaseModel):
    """Request to process a voice command (text mode for Phase 2)."""

    text: str = Field(..., min_length=1, description="Transcribed or typed command text")
    input_mode: str = Field(
        default="text",
        description="'voice' if from microphone, 'text' if typed",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID for context continuity; auto-generated if omitted",
    )


class IntentResult(BaseModel):
    """Parsed intent with entities."""

    intent: str
    confidence: float
    entities: dict
    raw_text: str


class VoiceProcessResponse(BaseModel):
    """Full response from voice command processing."""

    interaction_id: int
    session_id: str

    # What was understood
    recognized_text: str
    intent: str | None = None
    intent_confidence: float | None = None
    entities: dict = {}

    # Decision
    decision: str  # EXECUTE, CLARIFY, REJECT, ESCALATE
    decision_reason: str

    # Execution result (if EXECUTE)
    target_device: str | None = None
    requested_action: str | None = None
    execution_status: str | None = None
    new_device_state: str | None = None

    # Clarification (if CLARIFY)
    clarification_question: str | None = None
    requires_confirmation: bool = False

    # System message to display
    message: str
