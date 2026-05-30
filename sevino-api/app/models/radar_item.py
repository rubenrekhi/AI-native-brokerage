import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile


class RadarItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "radar_items"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_radar_items_user_id_symbol"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    context_blurb: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="ai_generated"
    )
    is_favorited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    bucket: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped[UserProfile] = relationship(back_populates="radar_items")
