import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.brokerage_account import BrokerageAccount
from app.models.plaid_item import PlaidItem
from app.models.user_profile import UserProfile


class AchRelationship(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ach_relationships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brokerage_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brokerage_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    plaid_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plaid_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    alpaca_relationship_id: Mapped[str] = mapped_column(Text, nullable=False)
    institution_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_mask: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="QUEUED"
    )

    user: Mapped[UserProfile] = relationship(back_populates="ach_relationships")
    brokerage_account: Mapped[BrokerageAccount] = relationship(
        back_populates="ach_relationships"
    )
    plaid_item: Mapped[Optional[PlaidItem]] = relationship(
        back_populates="ach_relationships"
    )
