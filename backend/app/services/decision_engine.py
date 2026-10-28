"""
Decision engine — reliability-aware command processing.

This is the core module of VoxEdge Phase 2.  Every voice or text command
passes through the decision engine, which considers:

  1. Parsed intent and confidence
  2. Whether the device is identifiable
  3. Whether the action is supported
  4. Recent interaction context (pronoun resolution)
  5. Risk classification
  6. Pending clarification state

The engine outputs one of four outcomes:
  EXECUTE  — valid, clear, authorized request → perform the action
  CLARIFY  — ambiguous target or action → ask a follow-up question
  REJECT   — unsupported, unauthorized, or invalid → refuse with explanation
  ESCALATE — emergency or high-risk request → trigger assistance workflow
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.context_service import ContextService, PendingClarification
from app.services.device_service import DeviceService
from app.services.intent_service import (
    CANCEL,
    CONFIRM,
    CONTROL_DEVICE,
    EMERGENCY,
    HELP,
    STATUS_CHECK,
    UNKNOWN,
    IntentResult,
)


# ── Decision outcomes ─────────────────────────────────────────────────────────
EXECUTE = "EXECUTE"
CLARIFY = "CLARIFY"
REJECT = "REJECT"
ESCALATE = "ESCALATE"


@dataclass
class Decision:
    """Structured output of the decision engine."""

    outcome: str  # EXECUTE, CLARIFY, REJECT, ESCALATE
    intent: str
    target_device: str | None = None
    requested_action: str | None = None
    confidence: float = 0.0
    reason: str = ""
    clarification_question: str | None = None
    requires_confirmation: bool = False
    message: str = ""
    entities: dict = field(default_factory=dict)


class DecisionEngine:
    """
    Processes an IntentResult and context to produce a Decision.

    This engine is deliberately implemented as a separate, testable
    component with no dependency on the API layer.
    """

    def __init__(
        self,
        db: Session,
        context: ContextService,
    ) -> None:
        self.device_service = DeviceService(db)
        self.context = context
        self.db = db

    def decide(
        self,
        intent_result: IntentResult,
        session_id: str,
    ) -> Decision:
        """
        Main entry point: route the intent to the appropriate handler.
        """
        intent = intent_result.intent

        if intent == EMERGENCY:
            return self._handle_emergency(intent_result)

        if intent == CANCEL:
            return self._handle_cancel(intent_result, session_id)

        if intent == CONFIRM:
            return self._handle_confirm(intent_result, session_id)

        if intent == HELP:
            return self._handle_help(intent_result)

        if intent == STATUS_CHECK:
            return self._handle_status(intent_result, session_id)

        if intent == CONTROL_DEVICE:
            return self._handle_control(intent_result, session_id)

        if intent == UNKNOWN:
            return self._handle_unknown(intent_result)

        return Decision(
            outcome=REJECT,
            intent=intent,
            reason="Unhandled intent type.",
            message="I didn't understand that. Try saying 'turn on the bedroom light' or 'help'.",
        )

    # ── Intent handlers ───────────────────────────────────────────────────

    def _handle_emergency(self, ir: IntentResult) -> Decision:
        return Decision(
            outcome=ESCALATE,
            intent=EMERGENCY,
            confidence=ir.confidence,
            reason="Emergency keyword detected.",
            message="Emergency assistance triggered. Notifying contacts.",
            entities=ir.entities,
        )

    def _handle_cancel(self, ir: IntentResult, session_id: str) -> Decision:
        pending = self.context.get_pending(session_id)
        if pending:
            self.context.clear_pending(session_id)
            return Decision(
                outcome=REJECT,
                intent=CANCEL,
                confidence=ir.confidence,
                reason="User cancelled the pending action.",
                message="Okay, the pending action has been cancelled.",
            )
        return Decision(
            outcome=REJECT,
            intent=CANCEL,
            confidence=ir.confidence,
            reason="Nothing to cancel.",
            message="There is nothing pending to cancel.",
        )

    def _handle_confirm(self, ir: IntentResult, session_id: str) -> Decision:
        pending = self.context.get_pending(session_id)
        if not pending:
            return Decision(
                outcome=REJECT,
                intent=CONFIRM,
                confidence=ir.confidence,
                reason="No pending action to confirm.",
                message="There is nothing pending to confirm.",
            )

        # Execute the pending action
        self.context.clear_pending(session_id)

        if pending.action and len(pending.candidates) == 1:
            device_id = pending.candidates[0]
            return Decision(
                outcome=EXECUTE,
                intent=CONTROL_DEVICE,
                target_device=device_id,
                requested_action=pending.action,
                confidence=0.9,
                reason="User confirmed the pending action.",
                message=f"Confirmed. Executing: {pending.action} on {device_id}.",
                entities=pending.entities,
            )

        return Decision(
            outcome=REJECT,
            intent=CONFIRM,
            reason="Pending action could not be resolved.",
            message="I couldn't resolve the pending action. Please try again.",
        )

    def _handle_help(self, ir: IntentResult) -> Decision:
        devices = self.device_service.list_devices()
        device_names = [d.name for d in devices]
        return Decision(
            outcome=REJECT,  # REJECT because no action is executed
            intent=HELP,
            confidence=ir.confidence,
            reason="Help request — listing capabilities.",
            message=(
                "I can control these devices: "
                + ", ".join(device_names)
                + ". Say things like 'turn on the bedroom light', "
                "'turn off the fan', or 'what is the status of the fan'. "
                "Say 'help me' or 'emergency' for assistance."
            ),
        )

    def _handle_status(self, ir: IntentResult, session_id: str) -> Decision:
        device_id = ir.entities.get("device")

        # Try context resolution if no device specified
        if device_id is None:
            device_id = self.context.get_last_device(session_id)

        if device_id is None:
            return Decision(
                outcome=CLARIFY,
                intent=STATUS_CHECK,
                confidence=ir.confidence,
                reason="No device specified for status check.",
                clarification_question="Which device would you like to check the status of?",
                message="Which device would you like to check?",
                entities=ir.entities,
            )

        device = self.device_service.get_device(device_id)
        if device is None:
            return Decision(
                outcome=REJECT,
                intent=STATUS_CHECK,
                target_device=device_id,
                confidence=ir.confidence,
                reason=f"Device '{device_id}' not found.",
                message=f"I couldn't find a device called '{device_id}'.",
            )

        return Decision(
            outcome=EXECUTE,
            intent=STATUS_CHECK,
            target_device=device_id,
            confidence=ir.confidence,
            reason="Status check for known device.",
            message=f"The {device.name} is currently {device.state}.",
            entities=ir.entities,
        )

    def _handle_control(self, ir: IntentResult, session_id: str) -> Decision:
        """
        Handle CONTROL_DEVICE intent — the most complex path.

        Checks:
          1. Is the action specified?
          2. Is the device specified and unambiguous?
          3. If ambiguous, can context resolve it?
          4. Is the action supported on this device?
        """
        action = ir.entities.get("action")
        device_id = ir.entities.get("device")
        device_type = ir.entities.get("device_type")
        is_ambiguous = ir.entities.get("device_ambiguous", False)
        has_pronoun = ir.entities.get("pronoun_reference", False)
        action_missing = ir.entities.get("action_missing", False)

        # ── Missing action ────────────────────────────────────────────────
        if action is None or action_missing:
            if device_id:
                return Decision(
                    outcome=CLARIFY,
                    intent=CONTROL_DEVICE,
                    target_device=device_id,
                    confidence=ir.confidence,
                    reason="Action not specified.",
                    clarification_question=f"What would you like to do with the {device_id}? Turn it on or off?",
                    message="I understood the device but not the action. What should I do with it?",
                    entities=ir.entities,
                )
            return Decision(
                outcome=CLARIFY,
                intent=CONTROL_DEVICE,
                confidence=ir.confidence,
                reason="Neither device nor action are clear.",
                clarification_question="I didn't catch that clearly. Could you say something like 'turn on the bedroom light'?",
                message="Could you repeat that more clearly?",
                entities=ir.entities,
            )

        # ── Pronoun resolution ("turn it off") ───────────────────────────
        if has_pronoun and device_id is None:
            resolved = self.context.get_last_device(session_id)
            if resolved:
                device_id = resolved
                ir.entities["device"] = resolved
                ir.entities["resolved_from_context"] = True
            else:
                return Decision(
                    outcome=CLARIFY,
                    intent=CONTROL_DEVICE,
                    requested_action=action,
                    confidence=ir.confidence,
                    reason="Pronoun reference but no recent device in context.",
                    clarification_question="Which device do you mean? I don't have a recent reference.",
                    message="Which device are you referring to?",
                    entities=ir.entities,
                )

        # ── Ambiguous device ("turn off the light" — which light?) ────────
        if is_ambiguous and device_id is None:
            # Try to narrow via device_type
            candidates = self.device_service.get_device_by_name_or_location(
                device_type=device_type
            )

            if len(candidates) == 1:
                device_id = candidates[0].id
                ir.entities["device"] = device_id
                ir.entities["resolved_from_type"] = True
            elif len(candidates) > 1:
                candidate_names = [c.name for c in candidates]
                candidate_ids = [c.id for c in candidates]

                # Try context to disambiguate
                last_device = self.context.get_last_device(session_id)
                if last_device and last_device in candidate_ids:
                    device_id = last_device
                    ir.entities["device"] = device_id
                    ir.entities["resolved_from_context"] = True
                else:
                    # Must ask the user
                    self.context.set_pending(
                        session_id,
                        PendingClarification(
                            interaction_id=0,  # will be updated by caller
                            question=f"Which one do you mean: {', '.join(candidate_names)}?",
                            intent=CONTROL_DEVICE,
                            entities=ir.entities,
                            candidates=candidate_ids,
                            action=action,
                        ),
                    )
                    return Decision(
                        outcome=CLARIFY,
                        intent=CONTROL_DEVICE,
                        requested_action=action,
                        confidence=ir.confidence,
                        reason=f"Multiple {device_type} devices found.",
                        clarification_question=f"Which one do you mean: {', '.join(candidate_names)}?",
                        message=f"There are multiple {device_type}s. Which one?",
                        entities=ir.entities,
                    )
            else:
                return Decision(
                    outcome=REJECT,
                    intent=CONTROL_DEVICE,
                    requested_action=action,
                    confidence=ir.confidence,
                    reason=f"No active {device_type} devices found.",
                    message=f"I don't have any {device_type} devices registered.",
                    entities=ir.entities,
                )

        # ── Missing device entirely ───────────────────────────────────────
        if device_id is None:
            return Decision(
                outcome=CLARIFY,
                intent=CONTROL_DEVICE,
                requested_action=action,
                confidence=ir.confidence,
                reason="No device specified and no context to resolve from.",
                clarification_question="Which device should I turn " + action.lower() + "?",
                message="Which device do you mean?",
                entities=ir.entities,
            )

        # ── Validate device exists ────────────────────────────────────────
        device = self.device_service.get_device(device_id)
        if device is None:
            return Decision(
                outcome=REJECT,
                intent=CONTROL_DEVICE,
                target_device=device_id,
                requested_action=action,
                confidence=ir.confidence,
                reason=f"Device '{device_id}' does not exist.",
                message=f"I don't know a device called '{device_id}'.",
                entities=ir.entities,
            )

        if not device.is_active:
            return Decision(
                outcome=REJECT,
                intent=CONTROL_DEVICE,
                target_device=device_id,
                requested_action=action,
                confidence=ir.confidence,
                reason=f"Device '{device.name}' is currently inactive.",
                message=f"The {device.name} is not available right now.",
                entities=ir.entities,
            )

        # ── Validate action is supported ──────────────────────────────────
        supported = json.loads(device.supported_actions)
        if action.upper() not in supported:
            return Decision(
                outcome=REJECT,
                intent=CONTROL_DEVICE,
                target_device=device_id,
                requested_action=action,
                confidence=ir.confidence,
                reason=f"Action '{action}' is not supported for {device.name}.",
                message=f"The {device.name} doesn't support '{action}'. Supported: {', '.join(supported)}.",
                entities=ir.entities,
            )

        # ── Low confidence → ask for confirmation ─────────────────────────
        if ir.confidence < settings.intent_confidence_threshold:
            self.context.set_pending(
                session_id,
                PendingClarification(
                    interaction_id=0,
                    question=f"Did you mean: turn {action} the {device.name}?",
                    intent=CONTROL_DEVICE,
                    entities=ir.entities,
                    candidates=[device_id],
                    action=action,
                ),
            )
            return Decision(
                outcome=CLARIFY,
                intent=CONTROL_DEVICE,
                target_device=device_id,
                requested_action=action,
                confidence=ir.confidence,
                requires_confirmation=True,
                reason=f"Low confidence ({ir.confidence:.2f} < {settings.intent_confidence_threshold}).",
                clarification_question=f"Did you mean: turn {action} the {device.name}?",
                message="I'm not fully sure I understood. Can you confirm?",
                entities=ir.entities,
            )

        # ── All checks passed → EXECUTE ───────────────────────────────────
        return Decision(
            outcome=EXECUTE,
            intent=CONTROL_DEVICE,
            target_device=device_id,
            requested_action=action,
            confidence=ir.confidence,
            reason="Valid command with sufficient confidence.",
            message=f"Turning {action} the {device.name}.",
            entities=ir.entities,
        )

    def _handle_unknown(self, ir: IntentResult) -> Decision:
        return Decision(
            outcome=REJECT,
            intent=UNKNOWN,
            confidence=0.0,
            reason="Intent could not be determined.",
            message=(
                "I didn't understand that command. "
                "Try 'turn on the bedroom light', 'fan off', or say 'help' for options."
            ),
            entities=ir.entities,
        )
