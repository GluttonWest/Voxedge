"""
Voice / command processing API.

POST /voice/process  — the main command pipeline endpoint.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.interaction import Interaction
from app.schemas.voice import VoiceProcessRequest, VoiceProcessResponse
from app.services.context_service import ContextService
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

router = APIRouter(prefix="/voice", tags=["voice"])

# ── Singletons (in-memory state — fine for single-process assistive device) ──
_intent_service = IntentService()
_context_service = ContextService()


@router.post("/process", response_model=VoiceProcessResponse)
def process_command(
    body: VoiceProcessRequest,
    db: Session = Depends(get_db),
):
    """
    Process a voice command or text input through the full pipeline:

      text → intent extraction → decision engine → execution
    """
    session_id = body.session_id or str(uuid.uuid4())
    text = body.text.strip()

    # ── 1. Intent extraction ──────────────────────────────────────────────
    intent_result = _intent_service.extract(text)

    # ── 2. Decision engine ────────────────────────────────────────────────
    engine = DecisionEngine(db=db, context=_context_service)
    decision = engine.decide(intent_result, session_id)

    # ── 3. Execute if decision is EXECUTE ─────────────────────────────────
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
        decision.message = exec_result["message"]

    elif decision.outcome == DEC_EXECUTE and decision.intent == STATUS_CHECK:
        execution_status = "SUCCESS"

    elif decision.outcome == DEC_ESCALATE:
        # Trigger emergency workflow
        emergency_service = EmergencyService(db)
        emergency_service.trigger(
            trigger_text=text,
            severity=decision.entities.get("severity", "HIGH"),
        )
        execution_status = "SUCCESS"

    # ── 4. Record interaction in the database ─────────────────────────────
    interaction = Interaction(
        session_id=session_id,
        raw_text=text,
        recognized_text=text,
        input_mode=body.input_mode,
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
    )
    db.add(interaction)
    db.commit()
    db.refresh(interaction)

    # ── 5. Update context on successful execution ─────────────────────────
    if decision.outcome == DEC_EXECUTE and decision.intent == CONTROL_DEVICE:
        _context_service.add_entry(
            session_id=session_id,
            device_id=decision.target_device,
            device_type=decision.entities.get("device_type"),
            action=decision.requested_action,
            intent=decision.intent,
        )

    # ── 6. Build response ─────────────────────────────────────────────────
    return VoiceProcessResponse(
        interaction_id=interaction.id,
        session_id=session_id,
        recognized_text=text,
        intent=intent_result.intent,
        intent_confidence=intent_result.confidence,
        entities=intent_result.entities,
        decision=decision.outcome,
        decision_reason=decision.reason,
        target_device=decision.target_device,
        requested_action=decision.requested_action,
        execution_status=execution_status,
        new_device_state=new_device_state,
        clarification_question=decision.clarification_question,
        requires_confirmation=decision.requires_confirmation,
        message=decision.message,
    )
