import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecurringInvestment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recurring_investments"
    __table_args__ = (
        Index("ix_recurring_investments_due", "status", "next_run_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_condition_kind: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="never"
    )
    end_on_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_after_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    executions_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )
    next_run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
