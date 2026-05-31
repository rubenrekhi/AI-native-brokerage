import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile


class DigestSnapshot(Base, UUIDPrimaryKeyMixin):
    """One day's curated digest for a user, persisted as a JSONB card stack.

    The ``(user_id, ny_local_date)`` unique constraint is the idempotency
    key the generator upserts on, so the morning cron and the lazy-fallback
    read path can both run without producing two rows for the same day.
    ``dismissed_at`` is the only mutable field after generation — set once
    when the user swipes the digest away, and never cleared.

    No ``updated_at``: a snapshot is immutable apart from the dismissal flip,
    so the generic ``TimestampMixin`` would only add noise.
    """

    __tablename__ = "digest_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "ny_local_date", name="uq_digest_snapshots_user_date"
        ),
        Index(
            "ix_digest_snapshots_user_date",
            "user_id",
            text("ny_local_date DESC"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    ny_local_date: Mapped[date] = mapped_column(Date, nullable=False)
    cards: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[UserProfile] = relationship(back_populates="digest_snapshots")
