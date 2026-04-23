"""Data access for `ach_relationships`. Soft-delete only; never hard-delete.

See docs/funding.md for the rationale.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ach_relationship import AchRelationship

# Alpaca lifecycle values (from their OpenAPI enum).
STATUS_QUEUED = "QUEUED"
STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_CANCEL_REQUESTED = "CANCEL_REQUESTED"

# Local soft-delete sentinel — written by `mark_canceled`, never by Alpaca.
STATUS_CANCELED = "CANCELED"


class AchRelationshipRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        brokerage_account_id: uuid.UUID,
        plaid_item_id: uuid.UUID | None,
        alpaca_relationship_id: str,
        institution_name: str | None = None,
        account_mask: str | None = None,
        account_type: str | None = None,
        nickname: str | None = None,
        status: str = "QUEUED",
    ) -> AchRelationship:
        rel = AchRelationship(
            user_id=user_id,
            brokerage_account_id=brokerage_account_id,
            plaid_item_id=plaid_item_id,
            alpaca_relationship_id=alpaca_relationship_id,
            institution_name=institution_name,
            account_mask=account_mask,
            account_type=account_type,
            nickname=nickname,
            status=status,
        )
        db.add(rel)
        await db.flush()
        return rel

    @staticmethod
    async def get_by_id(
        db: AsyncSession, rel_pk: uuid.UUID
    ) -> AchRelationship | None:
        result = await db.execute(
            select(AchRelationship).where(AchRelationship.id == rel_pk)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_alpaca_id(
        db: AsyncSession, alpaca_relationship_id: str
    ) -> AchRelationship | None:
        """Merge helper for GET /v1/funding/transfers."""
        result = await db.execute(
            select(AchRelationship).where(
                AchRelationship.alpaca_relationship_id == alpaca_relationship_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_active_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[AchRelationship]:
        """Excludes rows where status = 'CANCELED'."""
        result = await db.execute(
            select(AchRelationship).where(
                AchRelationship.user_id == user_id,
                AchRelationship.status != STATUS_CANCELED,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all_for_user(
        db: AsyncSession, user_id: uuid.UUID
    ) -> list[AchRelationship]:
        """Includes canceled. Used when merging transfer history display names."""
        result = await db.execute(
            select(AchRelationship).where(AchRelationship.user_id == user_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def mark_canceled(db: AsyncSession, rel_pk: uuid.UUID) -> None:
        rel = await AchRelationshipRepository.get_by_id(db, rel_pk)
        if rel is None:
            return
        rel.status = STATUS_CANCELED
        await db.flush()
