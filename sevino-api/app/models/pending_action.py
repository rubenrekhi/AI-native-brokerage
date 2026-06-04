import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PendingActionStatus:
    """Written lifecycle states. ``EXPIRED`` is derived at read time
    (``effective_status``), never stored.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


def effective_status(status: str, expires_at: datetime, *, now: datetime) -> str:
    """Overlay time-derived expiry on the stored, event-driven status.

    A still-``pending`` row past its window reads as ``expired`` without ever
    being written (see docs/ai/hil-actions.md §"Status is partly written,
    partly derived"). Every other state is a real stored value.

    ``expires_at`` and ``now`` must both be tz-aware (UTC); comparing a naive
    against an aware datetime raises ``TypeError``. The repository sources both
    correctly — this matters only for direct callers.
    """
    if status == PendingActionStatus.PENDING and expires_at <= now:
        return PendingActionStatus.EXPIRED
    return status


class PendingAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A consequential action proposed by the AI, awaiting an explicit user tap.

    The system of record for the human-in-the-loop framework: ``payload`` is
    executed verbatim on confirm by the ``action_type`` executor; ``preview``
    is exactly what the confirmation card showed (audit / tamper evidence).
    """

    __tablename__ = "pending_actions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_turn_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_turns.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_use_id: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=PendingActionStatus.PENDING
    )
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Backs the supersede sweep (WHERE conversation_id=? AND status='pending').
    __table_args__ = (
        Index(
            "ix_pending_actions_conversation_status",
            "conversation_id",
            "status",
        ),
    )
