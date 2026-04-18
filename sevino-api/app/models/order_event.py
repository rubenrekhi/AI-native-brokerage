import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.conversation import Conversation
from app.models.user_profile import UserProfile


class OrderEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "order_events"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    alpaca_order_id: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    qty: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    notional: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    filled_avg_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric, nullable=True
    )
    filled_qty: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped[UserProfile] = relationship(back_populates="order_events")
    conversation: Mapped[Optional[Conversation]] = relationship(
        back_populates="order_events"
    )
