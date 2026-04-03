import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile


class UserSettings(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    theme: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="system"
    )
    text_size: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="standard"
    )
    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    ai_internet_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    # Relationships
    user: Mapped[UserProfile] = relationship(back_populates="settings")
