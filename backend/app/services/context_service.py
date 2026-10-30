"""
Context Service — conversation state and multi-turn clarification management.

Tracks per-session context:
- Pronoun resolution ("turn it off" -> context device with validation)
- Multi-turn clarification question tracking & resolution
- Device state awareness
- Context window bounding and expiration
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.device import Device
from app.schemas.conversation import ContextSummaryResponse

logger = logging.getLogger(__name__)


@dataclass
class PendingClarification:
    """State for a clarification that is awaiting the user's response."""
    interaction_id: int | None
    question: str
    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)  # device IDs that could match
    action: str | None = None
    device_id: str | None = None
    needed_slot: str = "device"  # "device", "action", or "confirmation"
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > settings.context_expiry_seconds


@dataclass
class ContextEntry:
    """One entry in the interaction context window."""
    device_id: str | None
    device_type: str | None
    action: str | None
    intent: str
    raw_command: str = ""
    timestamp: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        return (time.time() - self.timestamp) > settings.context_expiry_seconds


class ContextService:
    """
    Per-session context manager.
    Tracks active context, resolves pronouns against device states,
    and manages multi-turn clarifications.
    """

    def __init__(self) -> None:
        self._history: dict[str, list[ContextEntry]] = {}
        self._pending: dict[str, PendingClarification] = {}

    # ── History management ────────────────────────────────────────────────

    def add_entry(
        self,
        session_id: str,
        device_id: str | None,
        device_type: str | None,
        action: str | None,
        intent: str,
        raw_command: str = "",
    ) -> None:
        """Record a successful interaction in the context window."""
        if session_id not in self._history:
            self._history[session_id] = []
        self._history[session_id].append(
            ContextEntry(
                device_id=device_id,
                device_type=device_type,
                action=action,
                intent=intent,
                raw_command=raw_command,
            )
        )
        # Keep only the last 10 entries per session
        self._history[session_id] = self._history[session_id][-10:]

    def get_last_device(self, session_id: str) -> str | None:
        """Return the device_id from the most recent non-expired context entry."""
        entries = self._history.get(session_id, [])
        for entry in reversed(entries):
            if entry.is_expired():
                break
            if entry.device_id is not None:
                return entry.device_id
        return None

    def get_last_action(self, session_id: str) -> str | None:
        """Return the action from the most recent non-expired context entry."""
        entries = self._history.get(session_id, [])
        for entry in reversed(entries):
            if entry.is_expired():
                break
            if entry.action is not None:
                return entry.action
        return None

    def get_last_command(self, session_id: str) -> str | None:
        """Return the raw command from the most recent entry."""
        entries = self._history.get(session_id, [])
        for entry in reversed(entries):
            if entry.is_expired():
                break
            if entry.raw_command:
                return entry.raw_command
        return None

    def get_last_device_type(self, session_id: str) -> str | None:
        """Return the device_type from the most recent non-expired entry."""
        entries = self._history.get(session_id, [])
        for entry in reversed(entries):
            if entry.is_expired():
                break
            if entry.device_type is not None:
                return entry.device_type
        return None

    def get_recent_devices(self, session_id: str, limit: int = 3) -> list[str]:
        """Return unique device IDs from recent non-expired context."""
        entries = self._history.get(session_id, [])
        seen: set[str] = set()
        result: list[str] = []
        for entry in reversed(entries):
            if entry.is_expired():
                break
            if entry.device_id and entry.device_id not in seen:
                seen.add(entry.device_id)
                result.append(entry.device_id)
                if len(result) >= limit:
                    break
        return result

    # ── Pronoun Resolution ────────────────────────────────────────────────

    def resolve_pronoun(
        self,
        session_id: str,
        requested_action: str | None,
        db_session: Session | None = None,
    ) -> tuple[str | None, str]:
        """
        Resolve a pronoun reference (e.g. "turn it off", "switch that on")
        using the recent conversation context and current device states.

        Returns:
            (resolved_device_id, reason)
            If context is insufficient, ambiguous, or expired, returns (None, reason).
        """
        entries = self._history.get(session_id, [])
        if not entries:
            return None, "Conversation history is empty; no prior device reference."

        recent_devices = self.get_recent_devices(session_id, limit=2)
        if not recent_devices:
            return None, "Prior context has expired."

        # If multiple different devices were mentioned recently, it's ambiguous
        if len(recent_devices) > 1:
            return (
                None,
                f"Multiple devices ({', '.join(recent_devices)}) were recently referenced.",
            )

        target_device_id = recent_devices[0]

        # Check device state coherence if database session is provided
        if db_session:
            device = db_session.query(Device).filter(Device.id == target_device_id).first()
            if device is None:
                return None, f"Device '{target_device_id}' no longer exists in system."

            # If action matches opposite of current state, strong confidence
            # e.g. device is ON and user says "turn it off" -> very coherent
            if requested_action and device.state == requested_action.upper():
                return (
                    target_device_id,
                    f"Resolved to {device.name} from context (device is already {device.state}).",
                )

        return (
            target_device_id,
            f"Resolved to '{target_device_id}' from immediate conversation turn.",
        )

    # ── Multi-turn Clarification Management ───────────────────────────────

    def set_pending(self, session_id: str, pending: PendingClarification) -> None:
        """Store a pending clarification for this session."""
        self._pending[session_id] = pending

    def get_pending(self, session_id: str) -> PendingClarification | None:
        """Retrieve the pending clarification, or None if expired/absent."""
        pending = self._pending.get(session_id)
        if pending is None:
            return None
        if pending.is_expired():
            del self._pending[session_id]
            return None
        return pending

    def clear_pending(self, session_id: str) -> None:
        """Remove any pending clarification for this session."""
        self._pending.pop(session_id, None)

    def resolve_clarification_response(
        self,
        session_id: str,
        text: str,
        db_session: Session | None = None,
    ) -> tuple[str, dict[str, Any] | None, str]:
        """
        Evaluate if a user utterance answers an active pending clarification question.

        Returns tuple:
            (status, resolution_data, explanation)
            status can be:
              - "RESOLVED": Successfully answered the question.
              - "CANCELED": User changed mind or canceled.
              - "UNRELATED": User asked an unrelated command or changed subject.
              - "UNCLEAR": Answer is vague or doesn't match expected slots.
              - "NONE": No pending clarification was active.
        """
        pending = self.get_pending(session_id)
        if not pending:
            return "NONE", None, "No active pending clarification."

        cleaned = text.lower().strip()

        # 1. Cancellation check
        cancel_words = {"cancel", "stop", "never mind", "nevermind", "forget it", "no", "abort"}
        if cleaned in cancel_words:
            self.clear_pending(session_id)
            return "CANCELED", None, "User canceled pending clarification."

        # 2. Emergency or topic change check
        emergency_words = {"help", "emergency", "doctor", "ambulance", "fallen", "fell", "pain", "hurt"}
        if any(w in cleaned for w in emergency_words):
            self.clear_pending(session_id)
            return "UNRELATED", {"topic": "emergency"}, "User shifted to emergency."

        # 3. Check if answering needed slot: "device"
        if pending.needed_slot == "device" or pending.action is not None:
            # Check device matches
            from app.services.intent_service import DEVICE_ALIASES

            matched_device: str | None = None
            matched_type: str | None = None

            for alias, (dev_id, dev_type, loc) in sorted(
                DEVICE_ALIASES.items(), key=lambda x: len(x[0]), reverse=True
            ):
                if re.search(rf"\b{re.escape(alias)}\b", cleaned):
                    matched_device = dev_id
                    matched_type = dev_type
                    break

            if matched_device and matched_device not in ("light", "lights"):
                # Exact device selected! (e.g. "the fan", "bedroom light", "living room light")
                resolved_action = pending.action or "ON"
                self.clear_pending(session_id)
                return (
                    "RESOLVED",
                    {
                        "device": matched_device,
                        "device_type": matched_type,
                        "action": resolved_action,
                        "intent": pending.intent,
                        "parent_interaction_id": pending.interaction_id,
                    },
                    f"Clarification answered: target device is '{matched_device}'.",
                )
            elif matched_device in ("light", "lights"):
                # Still ambiguous
                return "UNCLEAR", None, "Multiple lights still available. Please specify Bedroom Light or Living Room Light."

            # Check if user gave an unrelated command like "What is the weather?" or "Turn on something else"
            control_words = {"turn", "switch", "status", "check", "what", "is", "how", "who", "temperature"}
            words = set(cleaned.split())
            if words & control_words:
                self.clear_pending(session_id)
                return "UNRELATED", None, "User issued an unrelated command instead of answering."

            # Unclear answer (e.g. "banana", "random text")
            return "UNCLEAR", None, "Answer did not match the expected device choices."

        # 4. Check if answering needed slot: "action" (e.g. "turn on or off?")
        if pending.needed_slot == "action":
            from app.services.intent_service import ON_WORDS, OFF_WORDS
            if any(w in cleaned for w in ON_WORDS):
                self.clear_pending(session_id)
                return (
                    "RESOLVED",
                    {
                        "device": pending.device_id,
                        "action": "ON",
                        "intent": pending.intent,
                        "parent_interaction_id": pending.interaction_id,
                    },
                    "Clarification answered: action is 'ON'.",
                )
            if any(w in cleaned for w in OFF_WORDS):
                self.clear_pending(session_id)
                return (
                    "RESOLVED",
                    {
                        "device": pending.device_id,
                        "action": "OFF",
                        "intent": pending.intent,
                        "parent_interaction_id": pending.interaction_id,
                    },
                    "Clarification answered: action is 'OFF'.",
                )

            return "UNCLEAR", None, "Expected 'on' or 'off'."

        return "UNCLEAR", None, "Clarification could not be resolved."

    # ── Context Summary for UI/Diagnostics ────────────────────────────────

    def get_context_summary(
        self,
        session_id: str,
        db_session: Session | None = None,
    ) -> ContextSummaryResponse:
        """Assemble current context state for inspectability."""
        last_dev = self.get_last_device(session_id)
        last_act = self.get_last_action(session_id)
        last_cmd = self.get_last_command(session_id)
        last_dev_type = self.get_last_device_type(session_id)
        pending = self.get_pending(session_id)

        states: dict[str, str] = {}
        if db_session:
            devices = db_session.query(Device).all()
            for d in devices:
                states[d.id] = d.state

        return ContextSummaryResponse(
            session_id=session_id,
            last_device=last_dev,
            last_device_type=last_dev_type,
            last_action=last_act,
            last_command=last_cmd,
            has_pending_clarification=pending is not None,
            pending_clarification_question=pending.question if pending else None,
            pending_action=pending.action if pending else None,
            current_device_states=states,
        )

    def clear_session(self, session_id: str) -> None:
        """Remove all context for a session."""
        self._history.pop(session_id, None)
        self._pending.pop(session_id, None)
