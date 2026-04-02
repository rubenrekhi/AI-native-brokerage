import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


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

    # Relationships
    user: Mapped["UserProfile"] = relationship(back_populates="financial_profile")
