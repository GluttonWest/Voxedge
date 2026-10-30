"""
Decisions API — handle confirmation and clarification responses.

POST /decisions/confirm
"""

from __future__ import annotations

import json
import uuid

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.interaction import Interaction
from app.schemas.decision import ConfirmationRequest, ConfirmationResponse
from app.services.context_service import ContextService
from app.services.decision_engine import DecisionEngine
from app.services.decision_engine import EXECUTE as DEC_EXECUTE
from app.services.device_service import DeviceService
from app.services.intent_service import CONTROL_DEVICE, IntentService
from app.services.voice_auth_service import VoiceAuthService

router = APIRouter(prefix="/decisions", tags=["decisions"])

# Re-use the singletons from voice router
from app.api.voice import _context_service, _intent_service
_voice_auth_service = VoiceAuthService()


@router.post("/confirm", response_model=ConfirmationResponse)
def confirm_or_clarify(
    body: ConfirmationRequest,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    """
    Process a user's response to a clarification question or
    confirmation prompt.

    Security rules:
      - All device-control state changes require speaker verification.
      - Unauthenticated responses cannot execute device control actions.
    """
    session_id = body.session_id
    response_text = body.response.strip()

    # ── Check session authentication ─────────────────────────────────────────
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()

    has_valid_auth = False
    if token:
        valid, token_session_id = _voice_auth_service.verify_session_token(token)
        if valid and (token_session_id == session_id or not session_id):
            has_valid_auth = True

    is_enrolled = _voice_auth_service.is_enrolled()

    if not is_enrolled:
        interaction = Interaction(
            session_id=session_id,
            raw_text=response_text,
            recognized_text=response_text,
            input_mode="text",
            decision_outcome="REJECT",
            decision_reason="Voice profile not enrolled. Voice authentication is required.",
            execution_status="REJECTED",
        )
        db.add(interaction)
        db.commit()
        return ConfirmationResponse(
            interaction_id=interaction.id,
            session_id=session_id,
            decision="REJECT",
            decision_reason="Voice profile not enrolled. Voice authentication is required before commands can execute.",
            message="Voice profile not enrolled. Please enroll your voice first.",
        )

    if not has_valid_auth:
        interaction = Interaction(
            session_id=session_id,
            raw_text=response_text,
            recognized_text=response_text,
            input_mode="text",
            decision_outcome="REJECT",
            decision_reason="Unauthenticated request: valid speaker session required.",
            execution_status="REJECTED",
        )
        db.add(interaction)
        db.commit()
        return ConfirmationResponse(
            interaction_id=interaction.id,
            session_id=session_id,
            decision="REJECT",
            decision_reason="Unauthenticated clarification response: voice verification required to execute device control.",
            message="Voice authentication required. Clarification requests cannot be submitted without authentication.",
        )

    pending = _context_service.get_pending(session_id)

    # ── Run the response through intent extraction ────────────────────────
    intent_result = _intent_service.extract(response_text)

    engine = DecisionEngine(db=db, context=_context_service)
    decision = engine.decide(intent_result, session_id)

    # ── If the user confirmed and the pending action resolves, execute ────
    execution_status = None
    new_device_state = None

    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE:
        if not is_enrolled:
            decision.outcome = "REJECT"
            decision.reason = "Voice profile not enrolled. Voice authentication is required before commands can execute."
            decision.message = "Voice profile not enrolled. Please enroll your voice first."
            execution_status = "REJECTED"
        elif not has_valid_auth:
            decision.outcome = "REJECT"
            decision.reason = "Unauthenticated clarification response: voice verification required to execute device control."
            decision.message = "Voice authentication required. Device commands cannot be executed without speaker voice verification."
            execution_status = "REJECTED"
        else:
            device_service = DeviceService(db)
            exec_result = device_service.execute_action(
                device_id=decision.target_device,
                action=decision.requested_action,
            )
            execution_status = "SUCCESS" if exec_result["success"] else "FAILED"
            new_device_state = exec_result.get("new_state")
            decision.message = exec_result["message"]

            # Update context
            _context_service.add_entry(
                session_id=session_id,
                device_id=decision.target_device,
                device_type=decision.entities.get("device_type"),
                action=decision.requested_action,
                intent=decision.intent,
            )

    # ── If the response is itself a new command, also try that path ────────
    if (
        pending
        and decision.outcome != DEC_EXECUTE
        and pending.action
    ):
        # Try to interpret the response as a device selection
        from app.services.intent_service import DEVICE_ALIASES
        cleaned = response_text.lower().strip()
        for alias, (dev_id, dev_type, loc) in sorted(
            DEVICE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True
        ):
            if alias in cleaned and dev_id is not None:
                if not is_enrolled:
                    decision.outcome = "REJECT"
                    decision.reason = "Voice profile not enrolled. Voice authentication is required before commands can execute."
                    decision.message = "Voice profile not enrolled. Please enroll your voice first."
                    execution_status = "REJECTED"
                elif not has_valid_auth:
                    decision.outcome = "REJECT"
                    decision.reason = "Unauthenticated clarification response: voice verification required to execute device control."
                    decision.message = "Voice authentication required. Device commands cannot be executed without speaker voice verification."
                    execution_status = "REJECTED"
                else:
                    # Found a device — execute the pending action on it
                    device_service = DeviceService(db)
                    exec_result = device_service.execute_action(
                        device_id=dev_id,
                        action=pending.action,
                    )
                    execution_status = "SUCCESS" if exec_result["success"] else "FAILED"
                    new_device_state = exec_result.get("new_state")
                    _context_service.clear_pending(session_id)
                    _context_service.add_entry(
                        session_id=session_id,
                        device_id=dev_id,
                        device_type=dev_type,
                        action=pending.action,
                        intent=CONTROL_DEVICE,
                    )

                    decision.outcome = DEC_EXECUTE
                    decision.target_device = dev_id
                    decision.requested_action = pending.action
                    decision.message = exec_result["message"]
                    decision.reason = "Clarification resolved: user selected device."
                break

    # ── Record interaction ────────────────────────────────────────────────
    interaction = Interaction(
        session_id=session_id,
        raw_text=response_text,
        recognized_text=response_text,
        input_mode="text",
        intent=intent_result.intent,
        entities_json=json.dumps(intent_result.entities),
        intent_confidence=intent_result.confidence,
        decision_outcome=decision.outcome,
        decision_reason=decision.reason,
        target_device_id=decision.target_device,
        requested_action=decision.requested_action,
        clarification_question=decision.clarification_question,
        execution_status=execution_status,
        is_follow_up=True,
        parent_interaction_id=body.interaction_id,
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    return ConfirmationResponse(
        interaction_id=interaction.id,
        session_id=session_id,
        decision=decision.outcome,
        decision_reason=decision.reason,
        target_device=decision.target_device,
        requested_action=decision.requested_action,
        execution_status=execution_status,
        new_device_state=new_device_state,
        message=decision.message,
        clarification_question=decision.clarification_question,
    )
