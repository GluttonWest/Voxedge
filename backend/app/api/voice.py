"""
Voice / command processing and speaker authentication API.

Endpoints:
  GET  /voice/enrollment-status  — Check voice enrollment status
  POST /voice/enroll             — Enroll a speaker voice profile
  POST /voice/process-audio      — Authenticate speaker audio and execute command
  POST /voice/process            — Process command with backend auth enforcement
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models.interaction import Interaction
from app.schemas.conversation import ContextSummaryResponse, ConversationHistoryResponse
from app.schemas.voice import (
    EnrollmentStatusResponse,
    VoiceEnrollResponse,
    VoiceProcessRequest,
    VoiceProcessResponse,
)
from app.services.context_service import ContextService
from app.services.conversation_service import ConversationService
from app.services.decision_engine import DecisionEngine
from app.services.decision_engine import EXECUTE as DEC_EXECUTE
from app.services.decision_engine import ESCALATE as DEC_ESCALATE
from app.services.device_service import DeviceService
from app.services.emergency_service import EmergencyService
from app.services.intent_service import (
    CONTROL_DEVICE,
    STATUS_CHECK,
    IntentService,
)
from app.services.voice_auth_service import VoiceAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# ── Singletons ───────────────────────────────────────────────────────────────
_intent_service = IntentService()
_context_service = ContextService()
_voice_auth_service = VoiceAuthService()


# ── 1. Voice Enrollment Endpoints ───────────────────────────────────────────

@router.get("/enrollment-status", response_model=EnrollmentStatusResponse)
def get_enrollment_status():
    """Check whether a speaker voice profile is currently enrolled."""
    is_enrolled = _voice_auth_service.is_enrolled()
    threshold = settings.similarity_threshold
    message = (
        "Enrolled voice profile found."
        if is_enrolled
        else "No voice profile enrolled. Please enroll your voice first."
    )
    return EnrollmentStatusResponse(
        is_enrolled=is_enrolled,
        similarity_threshold=threshold,
        message=message,
    )


@router.post("/enroll", response_model=VoiceEnrollResponse)
async def enroll_voice(
    file: UploadFile = File(..., description="Audio recording (WAV format preferred)"),
    force: bool = Form(False, description="Explicit flag required to overwrite an existing profile"),
):
    """
    Enroll a voice sample to create or replace the speaker profile.

    Security requirements:
      - Enrollment is a separate operation from command execution.
      - Never automatically overwrites an existing profile.
      - Requires explicit authorization (force=True) to replace an existing profile.
      - Confirms enrollment only after successful creation and disk save.
    """
    audio_bytes = await file.read()
    if not audio_bytes or len(audio_bytes) == 0:
        raise HTTPException(
            status_code=400,
            detail="Audio sample is empty. Please record a voice sample before enrolling.",
        )

    success, message, extra = _voice_auth_service.enroll_voice(
        audio_bytes=audio_bytes, force=force
    )

    if not success:
        error_code = extra.get("error_code")
        if error_code == "PROFILE_EXISTS":
            raise HTTPException(
                status_code=409,
                detail=message,
            )
        raise HTTPException(
            status_code=400,
            detail=message,
        )

    return VoiceEnrollResponse(
        success=True,
        is_enrolled=True,
        message=message,
        dimensions=extra.get("dimensions", 256),
        similarity_threshold=settings.similarity_threshold,
    )


@router.delete("/profile")
def delete_voice_profile():
    """Delete existing voice profile to allow clean enrollment from scratch."""
    success = _voice_auth_service.delete_profile()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete profile.")
    return {"success": True, "message": "Voice profile removed. You can now enroll your voice from scratch."}


# ── 2. Automatic Authentication & Command Processing (Audio) ────────────────

@router.post("/process-audio", response_model=VoiceProcessResponse)
async def process_audio_command(
    file: UploadFile = File(..., description="Command audio recording"),
    session_id: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """
    Automatic speaker verification & command processing pipeline.

    Workflow:
      1. Check whether an enrolled voice profile exists. If not, reject immediately.
      2. Extract voice embedding from the audio using the speaker-verification model.
      3. Compare with enrolled embedding and calculate similarity score.
      4. Compare score against configured threshold.
      5. If score meets threshold: mark authenticated and proceed to speech recognition
         and intent processing.
      6. If score is below threshold or verification fails: reject command and execute
         no device action.
    """
    sid = session_id or str(uuid.uuid4())
    audio_bytes = await file.read()

    # ── Step 1: Check enrollment ────────────────────────────────────────────
    if not _voice_auth_service.is_enrolled():
        reason = "Voice profile not enrolled. Please enroll your voice first."
        interaction = Interaction(
            session_id=sid,
            raw_text="[Audio unauthenticated]",
            recognized_text="[Voice profile not enrolled]",
            input_mode="voice",
            speaker_verified=False,
            speaker_similarity=0.0,
            decision_outcome="REJECT",
            decision_reason=reason,
            execution_status="REJECTED",
        )
        db.add(interaction)
        db.commit()
        db.refresh(interaction)

        return VoiceProcessResponse(
            interaction_id=interaction.id,
            session_id=sid,
            recognized_text="",
            intent=None,
            decision="REJECT",
            decision_reason=reason,
            speaker_verified=False,
            speaker_similarity=0.0,
            similarity_threshold=settings.similarity_threshold,
            execution_status="REJECTED",
            message=reason,
        )

    # ── Step 2 & 3: Speaker verification & similarity calculation ───────────
    verified, similarity, verify_msg, failure_reason = _voice_auth_service.verify_speaker(audio_bytes)

    # ── Step 4: Verification failed or score below threshold ────────────────
    if not verified:
        logger.warning(
            "Speaker verification failed for session %s: %s (score=%.4f)",
            sid,
            failure_reason,
            similarity,
        )
        interaction = Interaction(
            session_id=sid,
            raw_text="[Audio voice verification failed]",
            recognized_text="[Voice not recognized]",
            input_mode="voice",
            speaker_verified=False,
            speaker_similarity=round(similarity, 4),
            decision_outcome="REJECT",
            decision_reason=failure_reason or verify_msg,
            execution_status="REJECTED",
        )
        db.add(interaction)
        db.commit()
        db.refresh(interaction)

        return VoiceProcessResponse(
            interaction_id=interaction.id,
            session_id=sid,
            recognized_text="",
            intent=None,
            decision="REJECT",
            decision_reason=failure_reason or verify_msg,
            speaker_verified=False,
            speaker_similarity=round(similarity, 4),
            similarity_threshold=settings.similarity_threshold,
            execution_status="REJECTED",
            message=verify_msg,
        )

    # ── Step 5: Speaker verified! Proceed to Speech Recognition (Vosk) ───────
    transcribed_text = _voice_auth_service.transcribe_audio(audio_bytes)
    auth_token = _voice_auth_service.create_session_token(sid, similarity)

    if not transcribed_text:
        interaction = Interaction(
            session_id=sid,
            raw_text="[Audio with no speech]",
            recognized_text="",
            input_mode="voice",
            speaker_verified=True,
            speaker_similarity=round(similarity, 4),
            decision_outcome="REJECT",
            decision_reason="Voice verified, but speech was empty or inaudible.",
            execution_status="REJECTED",
        )
        db.add(interaction)
        db.commit()
        db.refresh(interaction)

        return VoiceProcessResponse(
            interaction_id=interaction.id,
            session_id=sid,
            recognized_text="",
            intent=None,
            decision="REJECT",
            decision_reason="No speech was detected in audio.",
            speaker_verified=True,
            speaker_similarity=round(similarity, 4),
            similarity_threshold=settings.similarity_threshold,
            auth_token=auth_token,
            execution_status="REJECTED",
            message="Voice verified, but no speech was recognized. Please speak your command clearly.",
        )

    # ── Step 6: Intent Extraction & Decision Engine ─────────────────────────
    intent_result = _intent_service.extract(transcribed_text)
    engine = DecisionEngine(db=db, context=_context_service)
    decision = engine.decide(intent_result, sid)

    # ── Step 7: Execution (Authenticated path) ──────────────────────────────
    execution_status = None
    new_device_state = None

    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE:
        device_service = DeviceService(db)
        exec_result = device_service.execute_action(
            device_id=decision.target_device,
            action=decision.requested_action,
        )
        execution_status = "SUCCESS" if exec_result["success"] else "FAILED"
        new_device_state = exec_result.get("new_state")
        decision.message = f"Voice verified. {exec_result['message']}"

    elif decision.outcome == DEC_EXECUTE and decision.intent == STATUS_CHECK:
        execution_status = "SUCCESS"
        decision.message = f"Voice verified. {decision.message}"

    elif decision.outcome == DEC_ESCALATE:
        emergency_service = EmergencyService(db)
        emergency_service.trigger(
            trigger_text=transcribed_text,
            severity=decision.entities.get("severity", "HIGH"),
        )
        execution_status = "SUCCESS"
        decision.message = f"Voice verified. Emergency assistance triggered."

    # ── Step 8: Record interaction & apply retention policy ──────────────────
    interaction = Interaction(
        session_id=sid,
        raw_text=transcribed_text,
        recognized_text=transcribed_text,
        input_mode="voice",
        speaker_verified=True,
        speaker_similarity=round(similarity, 4),
        intent=intent_result.intent,
        entities_json=json.dumps(intent_result.entities),
        intent_confidence=intent_result.confidence,
        decision_outcome=decision.outcome,
        decision_reason=decision.reason,
        target_device_id=decision.target_device,
        requested_action=decision.requested_action,
        requires_confirmation=decision.requires_confirmation,
        clarification_question=decision.clarification_question,
        execution_status=execution_status,
        is_follow_up=decision.entities.get("resolved_from_clarification", False),
        parent_interaction_id=decision.entities.get("parent_interaction_id"),
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    ConversationService(db).apply_retention_policy(sid)

    # ── Step 9: Update context on successful execution ──────────────────────
    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE and execution_status == "SUCCESS":
        _context_service.add_entry(
            session_id=sid,
            device_id=decision.target_device,
            device_type=decision.entities.get("device_type"),
            action=decision.requested_action,
            intent=decision.intent,
            raw_command=transcribed_text,
        )

    # ── Step 10: Build response ─────────────────────────────────────────────
    return VoiceProcessResponse(
        interaction_id=interaction.id,
        session_id=sid,
        recognized_text=transcribed_text,
        intent=intent_result.intent,
        intent_confidence=intent_result.confidence,
        entities=intent_result.entities,
        structured_intent=intent_result.to_structured(),
        is_ambiguous=intent_result.is_ambiguous,
        requires_clarification=decision.outcome == "CLARIFY" or intent_result.requires_clarification,
        decision=decision.outcome,
        decision_reason=decision.reason,
        target_device=decision.target_device,
        requested_action=decision.requested_action,
        execution_status=execution_status,
        new_device_state=new_device_state,
        clarification_question=decision.clarification_question,
        requires_confirmation=decision.requires_confirmation,
        message=decision.message,
        speaker_verified=True,
        speaker_similarity=round(similarity, 4),
        similarity_threshold=settings.similarity_threshold,
        auth_token=auth_token,
    )


# ── 3. Text Processing with Backend Security Enforcement ────────────────────

@router.post("/process", response_model=VoiceProcessResponse)
def process_command(
    body: VoiceProcessRequest,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    """
    Process command text with backend authentication enforcement.

    Security rules:
      - All device-control state changes require authentication.
      - If no voice profile is enrolled, ordinary device commands are rejected.
      - If an unauthenticated text request attempts to change a device's state,
        it is rejected unless accompanied by a verified session auth token.
    """
    session_id = body.session_id or str(uuid.uuid4())
    text = body.text.strip()

    # ── Check enrollment ────────────────────────────────────────────────────
    is_enrolled = _voice_auth_service.is_enrolled()

    # ── Check if caller provided a valid session auth token ──────────────────
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()

    has_valid_auth = False
    if token:
        valid, token_session_id = _voice_auth_service.verify_session_token(token)
        if valid and (token_session_id == session_id or not body.session_id):
            has_valid_auth = True

    # ── 1. Intent extraction ────────────────────────────────────────────────
    intent_result = _intent_service.extract(text)

    # ── 2. Decision engine ──────────────────────────────────────────────────
    engine = DecisionEngine(db=db, context=_context_service)
    decision = engine.decide(intent_result, session_id)

    # ── 3. Security Enforcement on Device Control ───────────────────────────
    execution_status = None
    new_device_state = None

    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE:
        # Mandatory security check 1: profile must be enrolled
        if not is_enrolled:
            decision.outcome = "REJECT"
            decision.reason = "Voice profile not enrolled. Voice authentication is required before commands can execute."
            decision.message = "Voice profile not enrolled. Please enroll your voice first."
            execution_status = "REJECTED"

        # Mandatory security check 2: command must be authenticated
        elif not has_valid_auth:
            decision.outcome = "REJECT"
            decision.reason = "Unauthenticated command: voice verification required to execute device control."
            decision.message = "Voice authentication required. Device commands cannot be executed without speaker voice verification."
            execution_status = "REJECTED"

        else:
            # Authenticated session: execute action
            device_service = DeviceService(db)
            exec_result = device_service.execute_action(
                device_id=decision.target_device,
                action=decision.requested_action,
            )
            execution_status = "SUCCESS" if exec_result["success"] else "FAILED"
            new_device_state = exec_result.get("new_state")
            decision.message = exec_result["message"]
            if not exec_result["success"]:
                decision.reason = exec_result.get("error") or exec_result["message"]

    elif decision.outcome == DEC_EXECUTE and decision.intent == STATUS_CHECK:
        execution_status = "SUCCESS"

    elif decision.outcome == DEC_ESCALATE:
        emergency_service = EmergencyService(db)
        emergency_service.trigger(
            trigger_text=text,
            severity=decision.entities.get("severity", "HIGH"),
        )
        execution_status = "SUCCESS"

    # ── 4. Record interaction & apply retention policy ──────────────────────
    interaction = Interaction(
        session_id=session_id,
        raw_text=text,
        recognized_text=text,
        input_mode=body.input_mode,
        speaker_verified=has_valid_auth,
        intent=intent_result.intent,
        entities_json=json.dumps(intent_result.entities),
        intent_confidence=intent_result.confidence,
        decision_outcome=decision.outcome,
        decision_reason=decision.reason,
        target_device_id=decision.target_device,
        requested_action=decision.requested_action,
        requires_confirmation=decision.requires_confirmation,
        clarification_question=decision.clarification_question,
        execution_status=execution_status,
        is_follow_up=decision.entities.get("resolved_from_clarification", False),
        parent_interaction_id=decision.entities.get("parent_interaction_id"),
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    ConversationService(db).apply_retention_policy(session_id)

    # ── 5. Update context on successful execution ───────────────────────────
    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE and execution_status == "SUCCESS":
        _context_service.add_entry(
            session_id=session_id,
            device_id=decision.target_device,
            device_type=decision.entities.get("device_type"),
            action=decision.requested_action,
            intent=decision.intent,
            raw_command=text,
        )

    # ── 6. Build response ───────────────────────────────────────────────────
    return VoiceProcessResponse(
        interaction_id=interaction.id,
        session_id=session_id,
        recognized_text=text,
        intent=intent_result.intent,
        intent_confidence=intent_result.confidence,
        entities=intent_result.entities,
        structured_intent=intent_result.to_structured(),
        slm_proposal=decision.entities.get("slm_proposal"),
        is_ambiguous=intent_result.is_ambiguous,
        requires_clarification=decision.outcome == "CLARIFY" or intent_result.requires_clarification,
        decision=decision.outcome,
        decision_reason=decision.reason,
        target_device=decision.target_device,
        requested_action=decision.requested_action,
        execution_status=execution_status,
        new_device_state=new_device_state,
        clarification_question=decision.clarification_question,
        requires_confirmation=decision.requires_confirmation,
        message=decision.message,
        speaker_verified=has_valid_auth,
        similarity_threshold=settings.similarity_threshold,
    )


# ── 4. Conversation History & Context Endpoints ──────────────────────────────

@router.get("/history", response_model=ConversationHistoryResponse)
def get_conversation_history(
    session_id: str = Query(..., description="Session ID to retrieve turns for"),
    limit: int | None = Query(None, description="Max turns to return"),
    db: Session = Depends(get_db),
):
    """Retrieve bounded conversation history for a session."""
    conv_service = ConversationService(db)
    return conv_service.get_history(session_id=session_id, limit=limit)


@router.delete("/history")
def clear_conversation_history(
    session_id: str = Query(..., description="Session ID to clear"),
    db: Session = Depends(get_db),
):
    """Clear conversation history and active context for a session."""
    conv_service = ConversationService(db)
    deleted = conv_service.clear_history(session_id)
    _context_service.clear_session(session_id)
    return {"success": True, "deleted_turns": deleted}


@router.get("/context", response_model=ContextSummaryResponse)
def get_context_summary(
    session_id: str = Query(..., description="Session ID to inspect"),
    db: Session = Depends(get_db),
):
    """Inspect current active context, pending clarifications, and device states."""
    return _context_service.get_context_summary(session_id=session_id, db_session=db)

