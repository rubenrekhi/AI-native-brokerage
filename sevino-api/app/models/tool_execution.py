import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.model_invocation import ModelInvocation


class ToolExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tool_executions"

    model_invocation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_invocations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_tool_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tool_executions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_use_id: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_trace: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    ui_blocks_emitted: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    upstream_api_calls: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_invocation: Mapped[ModelInvocation] = relationship(
        back_populates="tool_executions"
    )
    parent: Mapped[Optional["ToolExecution"]] = relationship(
        remote_side="ToolExecution.id",
        back_populates="children",
    )
    children: Mapped[list["ToolExecution"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
    )
