import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile


class BrokerageAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "brokerage_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    alpaca_account_id: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False
    )
    account_status: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kyc_submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    kyc_results: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # Relationships
    user: Mapped[UserProfile] = relationship(back_populates="brokerage_account")
    ach_relationships: Mapped[list["AchRelationship"]] = relationship(
        back_populates="brokerage_account", cascade="all, delete-orphan"
    )
