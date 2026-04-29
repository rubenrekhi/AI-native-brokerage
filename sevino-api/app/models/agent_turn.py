import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user_profile import UserProfile

if TYPE_CHECKING:
    from app.models.model_invocation import ModelInvocation


class AgentTurn(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_turns"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    assistant_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    terminal_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    iterations_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_cache_read_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_cache_creation_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_thinking_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_cost_usd_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversation: Mapped[Conversation] = relationship()
    user: Mapped[UserProfile] = relationship(back_populates="agent_turns")
    user_message: Mapped[Optional[Message]] = relationship(
        foreign_keys=[user_message_id]
    )
    assistant_message: Mapped[Optional[Message]] = relationship(
        foreign_keys=[assistant_message_id]
    )
    invocations: Mapped[list["ModelInvocation"]] = relationship(
        back_populates="agent_turn",
        cascade="all, delete-orphan",
        order_by="ModelInvocation.iteration_index",
    )
