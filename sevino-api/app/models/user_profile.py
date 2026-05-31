import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.ach_relationship import AchRelationship
    from app.models.agent_turn import AgentTurn
    from app.models.brokerage_account import BrokerageAccount
    from app.models.conversation import Conversation
    from app.models.digest import DigestSnapshot
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
    phone_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    street_address: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    city: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    middle_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country_of_citizenship: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country_of_birth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country_of_tax_residence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Last four digits of SSN, captured at KYC submission. The full SSN is
    # forwarded to Alpaca and never persisted; we only retain last-4 so the
    # settings UI can display `•••-••-NNNN`.
    tax_id_last_4: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disclosures: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    agreements_signed: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    risk_disclosure_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attribution_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    onboarding_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_radar_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
    agent_turns: Mapped[list["AgentTurn"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    digest_snapshots: Mapped[list["DigestSnapshot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
