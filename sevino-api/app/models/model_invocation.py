import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.agent_turn import AgentTurn
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.tool_execution import ToolExecution


class ModelInvocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "model_invocations"

    agent_turn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_turns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    iteration_index: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_role: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="main"
    )
    request_system: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    request_tools: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    response_content: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    stop_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cache_read_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cache_creation_input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    thinking_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    cost_usd_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agent_turn: Mapped[AgentTurn] = relationship(back_populates="invocations")
    tool_executions: Mapped[list["ToolExecution"]] = relationship(
        back_populates="model_invocation",
        cascade="all, delete-orphan",
    )
