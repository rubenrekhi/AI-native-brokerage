import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user_profile import UserProfile

if TYPE_CHECKING:
    from app.models.ach_relationship import AchRelationship


class PlaidItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "plaid_items"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plaid_item_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    plaid_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    plaid_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    institution_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_mask: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )

    user: Mapped[UserProfile] = relationship(back_populates="plaid_items")
    ach_relationships: Mapped[list["AchRelationship"]] = relationship(
        back_populates="plaid_item",
        passive_deletes=True,
    )
