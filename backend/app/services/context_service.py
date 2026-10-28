"""
Context service — lightweight conversation state management.

Tracks recent interactions per session so the decision engine can:
- Resolve pronoun references ("turn it off" → last device)
- Ask clarification when the target is ambiguous
- Prevent stale context from being used after CONTEXT_EXPIRY_SECONDS
- Manage pending clarification state
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from app.core.config import settings


@dataclass
class PendingClarification:
    """State for a clarification that is awaiting the user's response."""
    interaction_id: int
    question: str
    intent: str
    entities: dict
    candidates: list[str]  # device IDs that could match
    action: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class ContextEntry:
    """One entry in the interaction context window."""
    device_id: str | None
    device_type: str | None
    action: str | None
    intent: str
    timestamp: float = field(default_factory=time.time)


class ContextService:
    """
    Per-session context manager.

    Stores context in-memory (keyed by session_id).  This is appropriate
    for a single-user assistive device; for multi-user production use,
    context would be stored in Redis or the database.
    """

    def __init__(self) -> None:
        # session_id → list of recent ContextEntry (newest last)
        self._history: dict[str, list[ContextEntry]] = {}
        # session_id → pending clarification
        self._pending: dict[str, PendingClarification] = {}

    # ── History management ────────────────────────────────────────────────

    def add_entry(
        self,
        session_id: str,
        device_id: str | None,
        device_type: str | None,
        action: str | None,
        intent: str,
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
            )
        )
        # Keep only the last 10 entries
        self._history[session_id] = self._history[session_id][-10:]

    def get_last_device(self, session_id: str) -> str | None:
        """
        Return the device_id from the most recent non-expired context entry.

        Returns None if no recent device is available or context has expired.
        """
        entries = self._history.get(session_id, [])
        cutoff = time.time() - settings.context_expiry_seconds
        for entry in reversed(entries):
            if entry.timestamp < cutoff:
                break  # everything older is also stale
            if entry.device_id is not None:
                return entry.device_id
        return None

    def get_last_device_type(self, session_id: str) -> str | None:
        """Return the device_type from the most recent non-expired entry."""
        entries = self._history.get(session_id, [])
        cutoff = time.time() - settings.context_expiry_seconds
        for entry in reversed(entries):
            if entry.timestamp < cutoff:
                break
            if entry.device_type is not None:
                return entry.device_type
        return None

    def get_recent_devices(self, session_id: str, limit: int = 3) -> list[str]:
        """Return unique device IDs from recent non-expired context."""
        entries = self._history.get(session_id, [])
        cutoff = time.time() - settings.context_expiry_seconds
        seen: set[str] = set()
        result: list[str] = []
        for entry in reversed(entries):
            if entry.timestamp < cutoff:
                break
            if entry.device_id and entry.device_id not in seen:
                seen.add(entry.device_id)
                result.append(entry.device_id)
                if len(result) >= limit:
                    break
        return result

    # ── Pending clarification management ──────────────────────────────────

    def set_pending(self, session_id: str, pending: PendingClarification) -> None:
        """Store a pending clarification for this session."""
        self._pending[session_id] = pending

    def get_pending(self, session_id: str) -> PendingClarification | None:
        """Retrieve the pending clarification, or None if expired/absent."""
        pending = self._pending.get(session_id)
        if pending is None:
            return None
        # Expire pending clarifications after context_expiry_seconds
        if time.time() - pending.created_at > settings.context_expiry_seconds:
            del self._pending[session_id]
            return None
        return pending

    def clear_pending(self, session_id: str) -> None:
        """Remove any pending clarification for this session."""
        self._pending.pop(session_id, None)

    def clear_session(self, session_id: str) -> None:
        """Remove all context for a session."""
        self._history.pop(session_id, None)
        self._pending.pop(session_id, None)
