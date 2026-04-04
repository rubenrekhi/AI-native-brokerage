import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.ach_relationship import AchRelationship
    from app.models.brokerage_account import BrokerageAccount
    from app.models.conversation import Conversation
    from app.models.order_event import OrderEvent
    from app.models.plaid_item import PlaidItem
    from app.models.radar_item import RadarItem
    from app.models.user_financial_profile import UserFinancialProfile
    from app.models.user_settings import UserSettings


class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"

    # PK mirrors auth.users.id — not auto-generated
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    onboarding_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    financial_profile: Mapped[Optional["UserFinancialProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    settings: Mapped[Optional["UserSettings"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    brokerage_account: Mapped[Optional["BrokerageAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    plaid_items: Mapped[list["PlaidItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    ach_relationships: Mapped[list["AchRelationship"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    radar_items: Mapped[list["RadarItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    order_events: Mapped[list["OrderEvent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
