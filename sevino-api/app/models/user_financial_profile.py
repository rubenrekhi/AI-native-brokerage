import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import Date, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile


class UserFinancialProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_financial_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    annual_income: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    net_worth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_tolerance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    investment_goals: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    time_horizon: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    financial_worries: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
    liquid_net_worth: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    income_stability: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_scenario_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    max_loss_tolerance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    employment_info: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    funding_sources: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )

    user: Mapped[UserProfile] = relationship(back_populates="financial_profile")
