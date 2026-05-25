"""Data access for `plaid_items`. Owns encrypt/decrypt of `plaid_access_token`.

Plaintext access tokens exist only in-memory inside this module and the
FundingService layer. They are encrypted via `app.services.encryption` on the
way in and decrypted on the way out. Never log the plaintext value.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plaid_item import PlaidItem
from app.services.encryption import decrypt, encrypt

# Known values for plaid_items.status (free-form TEXT column)
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_REQUIRES_REAUTH = "requires_reauth"


class PlaidItemRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        plaid_item_id: str,
        plaid_access_token_plaintext: str,
        plaid_account_id: str,
        institution_name: str | None = None,
        account_mask: str | None = None,
        account_name: str | None = None,
    ) -> PlaidItem:
        item = PlaidItem(
            user_id=user_id,
            plaid_item_id=plaid_item_id,
            plaid_access_token=encrypt(plaid_access_token_plaintext),
            plaid_account_id=plaid_account_id,
            institution_name=institution_name,
            account_mask=account_mask,
            account_name=account_name,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def get_by_id(
        db: AsyncSession, item_pk: uuid.UUID
    ) -> PlaidItem | None:
        result = await db.execute(select(PlaidItem).where(PlaidItem.id == item_pk))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_plaid_item_id(
        db: AsyncSession, plaid_item_id: str
    ) -> PlaidItem | None:
        """Idempotency lookup for `link-bank` retries."""
        result = await db.execute(
            select(PlaidItem).where(PlaidItem.plaid_item_id == plaid_item_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_access_token_plaintext(
        db: AsyncSession, item_pk: uuid.UUID
    ) -> str | None:
        """Decrypt and return. Returns None if the row is missing."""
        item = await PlaidItemRepository.get_by_id(db, item_pk)
        if item is None:
            return None
        return decrypt(item.plaid_access_token)

    @staticmethod
    async def mark_inactive(db: AsyncSession, item_pk: uuid.UUID) -> None:
        item = await PlaidItemRepository.get_by_id(db, item_pk)
        if item is None:
            return
        item.status = "inactive"
        await db.flush()

    @staticmethod
    async def mark_requires_reauth(
        db: AsyncSession, plaid_item_id: str
    ) -> PlaidItem | None:
        """Webhook entrypoint — lookup by Plaid's item_id string, not our PK.

        Returns None when the webhook references an item we never linked, so
        the handler can ack Plaid (200) without raising.
        """
        item = await PlaidItemRepository.get_by_plaid_item_id(db, plaid_item_id)
        if item is None:
            return None
        item.status = STATUS_REQUIRES_REAUTH
        await db.flush()
        return item

    @staticmethod
    async def mark_active(db: AsyncSession, item_pk: uuid.UUID) -> None:
        item = await PlaidItemRepository.get_by_id(db, item_pk)
        if item is None:
            return
        item.status = STATUS_ACTIVE
        await db.flush()
