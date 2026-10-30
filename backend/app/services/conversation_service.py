"""
Conversation History Service for VoxEdge.

Stores and manages conversation turns, interactions, clarification dialogues,
and execution outcomes. Enforces configurable retention limits and strictly avoids
storing raw audio recordings or voice embeddings.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.interaction import Interaction
from app.schemas.conversation import ConversationHistoryResponse, ConversationTurn

logger = logging.getLogger(__name__)


class ConversationService:
    """Manages persistent conversation history and retention policies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record_turn(
        self,
        session_id: str,
        user_text: str | None,
        recognized_text: str | None,
        input_mode: str,
        intent: str | None,
        entities: dict[str, Any] | None,
        decision_outcome: str | None,
        decision_reason: str | None,
        target_device_id: str | None = None,
        requested_action: str | None = None,
        clarification_question: str | None = None,
        execution_status: str | None = None,
        execution_error: str | None = None,
        is_follow_up: bool = False,
        parent_interaction_id: int | None = None,
        speaker_verified: bool | None = None,
        speaker_similarity: float | None = None,
        requires_confirmation: bool = False,
    ) -> Interaction:
        """
        Record an interaction turn in the database.
        Applies retention policy to keep history bounded.
        """
        entities_json = json.dumps(entities) if entities else None

        interaction = Interaction(
            session_id=session_id,
            raw_text=user_text,
            recognized_text=recognized_text or user_text,
            input_mode=input_mode,
            speaker_verified=speaker_verified,
            speaker_similarity=speaker_similarity,
            intent=intent,
            entities_json=entities_json,
            decision_outcome=decision_outcome,
            decision_reason=decision_reason,
            target_device_id=target_device_id,
            requested_action=requested_action,
            requires_confirmation=requires_confirmation,
            clarification_question=clarification_question,
            execution_status=execution_status,
            execution_error=execution_error,
            is_follow_up=is_follow_up,
            parent_interaction_id=parent_interaction_id,
        )
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)

        # Apply retention policy after adding
        self.apply_retention_policy(session_id)

        return interaction

    def get_history(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> ConversationHistoryResponse:
        """Retrieve recent conversation turns for a session."""
        effective_limit = limit or settings.max_conversation_history
        effective_limit = min(effective_limit, settings.max_conversation_history)

        interactions = (
            self.db.query(Interaction)
            .filter(Interaction.session_id == session_id)
            .order_by(desc(Interaction.created_at), desc(Interaction.id))
            .limit(effective_limit)
            .all()
        )
        # Order chronologically (oldest to newest)
        interactions.reverse()

        turns: list[ConversationTurn] = []
        for item in interactions:
            # Determine assistant response text
            assistant_msg = item.decision_reason or item.decision_outcome
            if item.clarification_question:
                assistant_msg = item.clarification_question

            turns.append(
                ConversationTurn(
                    id=item.id,
                    session_id=item.session_id,
                    timestamp=item.created_at.isoformat(),
                    user_text=item.recognized_text or item.raw_text,
                    assistant_response=assistant_msg,
                    intent=item.intent,
                    device_id=item.target_device_id,
                    action=item.requested_action,
                    decision_outcome=item.decision_outcome,
                    execution_status=item.execution_status,
                    is_clarification=bool(item.clarification_question),
                    clarification_question=item.clarification_question,
                    clarification_answer=item.raw_text if item.is_follow_up else None,
                    is_follow_up=item.is_follow_up,
                )
            )

        total = self.db.query(Interaction).filter(Interaction.session_id == session_id).count()

        return ConversationHistoryResponse(
            session_id=session_id,
            total_turns=total,
            max_limit=settings.max_conversation_history,
            turns=turns,
        )

    def apply_retention_policy(self, session_id: str) -> int:
        """
        Enforce retention limit. If a session exceeds max_conversation_history,
        deletes the oldest rows to maintain bounded storage.
        """
        max_allowed = settings.max_conversation_history
        total_count = (
            self.db.query(Interaction)
            .filter(Interaction.session_id == session_id)
            .count()
        )

        if total_count <= max_allowed:
            return 0

        excess = total_count - max_allowed
        # Find IDs of the oldest excess rows
        oldest_rows = (
            self.db.query(Interaction.id)
            .filter(Interaction.session_id == session_id)
            .order_by(Interaction.created_at.asc(), Interaction.id.asc())
            .limit(excess)
            .all()
        )
        oldest_ids = [row[0] for row in oldest_rows]

        if oldest_ids:
            (
                self.db.query(Interaction)
                .filter(Interaction.id.in_(oldest_ids))
                .delete(synchronize_session=False)
            )
            self.db.commit()
            logger.info(
                "Retention policy trimmed %d oldest interactions for session %s",
                len(oldest_ids),
                session_id,
            )
            return len(oldest_ids)

        return 0

    def clear_history(self, session_id: str) -> int:
        """Clear conversation history for a given session."""
        deleted = (
            self.db.query(Interaction)
            .filter(Interaction.session_id == session_id)
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return deleted

