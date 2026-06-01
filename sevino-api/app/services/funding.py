"""Funding orchestrator: bank linking (Plaid 3→4→5 + Alpaca ACH) and transfers.

Canonical reference: docs/funding.md.
"""

import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.ach_relationship import AchRelationship
from app.repositories.ach_relationship import (
    STATUS_APPROVED as ACH_RELATIONSHIP_STATUS_APPROVED,
)
from app.repositories.ach_relationship import (
    STATUS_CANCEL_REQUESTED as ACH_RELATIONSHIP_STATUS_CANCEL_REQUESTED,
)
from app.repositories.ach_relationship import (
    STATUS_CANCELED as ACH_RELATIONSHIP_STATUS_CANCELED,
)
from app.repositories.ach_relationship import AchRelationshipRepository
from app.repositories.brokerage_account import (
    STATUS_ACTIVE as BROKERAGE_ACCOUNT_STATUS_ACTIVE,
)
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.repositories.plaid_item import PlaidItemRepository
from app.services.alpaca_broker import (
    ALPACA_TRANSFER_NOT_CANCELABLE_CODE,
    CANCELABLE_TRANSFER_STATUSES,
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.plaid import PlaidService

logger = structlog.get_logger(__name__)

class FundingService:

    @staticmethod
    async def create_link_token(
        *, plaid: PlaidService, user_id: uuid.UUID
    ) -> str:
        token = await plaid.create_link_token(user_id=str(user_id))
        logger.info("link_token_created", user_id=str(user_id))
        return token

    @staticmethod
    async def link_bank(
        db: AsyncSession,
        *,
        plaid: PlaidService,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        public_token: str,
        account_id: str,
        institution_name: str | None = None,
        account_mask: str | None = None,
        account_name: str | None = None,
        nickname: str | None = None,
    ) -> AchRelationship:
        """Orchestrate Plaid exchange → processor token → Alpaca ACH relationship.

        Idempotent on Plaid `item_id`: retries by the client for the same
        underlying Plaid item will not create duplicate rows at Alpaca or in
        our DB.
        """
        brokerage = await _require_active_brokerage(db, user_id)

        access_token, plaid_item_id = await plaid.exchange_public_token(
            public_token=public_token
        )

        existing_item = await PlaidItemRepository.get_by_plaid_item_id(
            db, plaid_item_id
        )
        if existing_item is not None:
            existing_rel = await _find_active_relationship_for_item(db, existing_item.id)
            if existing_rel is not None:
                logger.info(
                    "link_bank_idempotent_hit",
                    user_id=str(user_id),
                    plaid_item_id=str(existing_item.id),
                    alpaca_relationship_id=existing_rel.alpaca_relationship_id,
                )
                return existing_rel

        processor_token = await plaid.create_processor_token(
            access_token=access_token, account_id=account_id
        )

        try:
            alpaca_relationship = await alpaca.create_ach_relationship(
                brokerage.alpaca_account_id, processor_token=processor_token
            )
        except AlpacaBrokerError as exc:
            if exc.status_code == 409:
                logger.warning(
                    "link_bank_duplicate_attempt",
                    user_id=str(user_id),
                    alpaca_message=exc.message,
                )
                raise ConflictError(
                    "This bank account is already linked.",
                    code="BANK_ALREADY_LINKED",
                ) from exc
            raise

        # From this point on the Alpaca relationship exists remotely. If any
        # step below fails (DB write, concurrent race that resolves to another
        # request's row), we must compensate by deleting our Alpaca row so it
        # doesn't orphan. The `alpaca_persisted` flag flips true only when the
        # local ACH relationship row successfully points at our Alpaca id.
        alpaca_relationship_id = alpaca_relationship["id"]
        alpaca_persisted = False
        try:
            try:
                plaid_item = await PlaidItemRepository.create(
                    db,
                    user_id=user_id,
                    plaid_item_id=plaid_item_id,
                    plaid_access_token_plaintext=access_token,
                    plaid_account_id=account_id,
                    institution_name=institution_name,
                    account_mask=account_mask,
                    account_name=account_name,
                )
            except IntegrityError:
                # Race: another concurrent link-bank request inserted this
                # plaid_item_id between our fast-path lookup and this insert.
                await db.rollback()
                existing_item = await PlaidItemRepository.get_by_plaid_item_id(
                    db, plaid_item_id
                )
                if existing_item is None:
                    raise
                existing_rel = await _find_active_relationship_for_item(
                    db, existing_item.id
                )
                if existing_rel is not None:
                    logger.info(
                        "link_bank_race_resolved",
                        user_id=str(user_id),
                        plaid_item_id=str(existing_item.id),
                        alpaca_relationship_id=existing_rel.alpaca_relationship_id,
                    )
                    # Our Alpaca row is now orphaned; the finally block
                    # compensates. Return the row the other request persisted.
                    return existing_rel
                plaid_item = existing_item

            relationship = await AchRelationshipRepository.create(
                db,
                user_id=user_id,
                brokerage_account_id=brokerage.id,
                plaid_item_id=plaid_item.id,
                alpaca_relationship_id=alpaca_relationship_id,
                institution_name=institution_name,
                account_mask=account_mask,
                account_type=alpaca_relationship.get("bank_account_type"),
                nickname=nickname or alpaca_relationship.get("nickname"),
                status=alpaca_relationship.get("status", "QUEUED"),
            )
            alpaca_persisted = True
            logger.info(
                "link_bank_completed",
                user_id=str(user_id),
                plaid_item_id=str(plaid_item.id),
                alpaca_relationship_id=relationship.alpaca_relationship_id,
                status=relationship.status,
            )
            return relationship
        finally:
            if not alpaca_persisted:
                await _compensate_alpaca_ach_relationship(
                    alpaca=alpaca,
                    alpaca_account_id=brokerage.alpaca_account_id,
                    alpaca_relationship_id=alpaca_relationship_id,
                    user_id=user_id,
                )

    @staticmethod
    async def create_reauth_link_token(
        db: AsyncSession,
        *,
        plaid: PlaidService,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
    ) -> str:
        """Mint a Plaid update-mode link token for an existing relationship.

        The existing `access_token` stays valid after a successful update-mode
        Link; iOS doesn't exchange a new public token. Raises `NotFoundError`
        when the relationship has no `plaid_item_id` (FK was set NULL by an
        earlier hard-delete) since we can't re-auth without an access token.
        """
        rel = await _load_relationship_for_user(db, user_id, relationship_pk)
        if rel.plaid_item_id is None:
            raise NotFoundError(
                "This bank link can no longer be re-authenticated; please re-link."
            )
        access_token = await PlaidItemRepository.get_access_token_plaintext(
            db, rel.plaid_item_id
        )
        assert access_token is not None
        token = await plaid.create_update_link_token(
            user_id=str(user_id), access_token=access_token
        )
        logger.info(
            "reauth_link_token_created",
            user_id=str(user_id),
            relationship_pk=str(rel.id),
            plaid_item_pk=str(rel.plaid_item_id),
        )
        return token

    @staticmethod
    async def mark_reauth_complete(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
    ) -> None:
        """Flip the linked `plaid_items.status` back to `active` after a
        successful update-mode Link. Idempotent: a relationship whose
        `plaid_item_id` is NULL (rare race or post-cleanup) is a no-op since
        the user-visible re-auth already succeeded at Plaid.
        """
        rel = await _load_relationship_for_user(db, user_id, relationship_pk)
        if rel.plaid_item_id is None:
            return
        await PlaidItemRepository.mark_active(db, rel.plaid_item_id)
        logger.info(
            "reauth_completed",
            user_id=str(user_id),
            relationship_pk=str(rel.id),
            plaid_item_pk=str(rel.plaid_item_id),
        )

    @staticmethod
    async def list_active_ach_relationships(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
    ) -> list[AchRelationship]:
        """Return the user's non-canceled relationships, refreshed from Alpaca.

        Alpaca does not push `ach_relationship` status over SSE (only transfer
        status). So we refresh on read: the one-shot Alpaca call keeps the
        local `status` column aligned with reality when the user looks at
        their bank list. If the brokerage isn't ACTIVE or no rows exist, we
        skip the call. If Alpaca itself is unreachable, we log and fall back
        to local state — this endpoint is informational, never a money
        precondition (`create_transfer` does its own fresh refresh before
        any transfer), so returning stale status is safe.
        """
        relationships = await AchRelationshipRepository.list_active_for_user(db, user_id)
        if not relationships:
            return relationships

        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if (
            brokerage is not None
            and brokerage.account_status == BROKERAGE_ACCOUNT_STATUS_ACTIVE
        ):
            try:
                await _refresh_statuses_from_alpaca(
                    db,
                    alpaca=alpaca,
                    alpaca_account_id=brokerage.alpaca_account_id,
                    relationships=relationships,
                )
            except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
                logger.warning(
                    "ach_relationship_refresh_failed",
                    user_id=str(user_id),
                    error=str(exc),
                )
        return relationships

    @staticmethod
    async def unlink_bank(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
    ) -> None:
        """DELETE at Alpaca first; on success or 404, soft-delete locally.
        On 5xx, AlpacaBrokerUnavailableError bubbles up and the row is untouched.
        """
        rel = await _load_relationship_for_user(db, user_id, relationship_pk)
        brokerage = await _require_active_brokerage(db, user_id)

        try:
            await alpaca.delete_ach_relationship(
                brokerage.alpaca_account_id, rel.alpaca_relationship_id
            )
        except NotFoundError:
            logger.info(
                "alpaca_ach_relationship_already_gone",
                relationship_pk=str(rel.id),
                alpaca_relationship_id=rel.alpaca_relationship_id,
            )
        except AlpacaBrokerUnavailableError:
            logger.warning(
                "unlink_failed_alpaca_unavailable",
                user_id=str(user_id),
                relationship_pk=str(rel.id),
                alpaca_relationship_id=rel.alpaca_relationship_id,
            )
            raise

        await AchRelationshipRepository.mark_canceled(db, rel.id)
        logger.info(
            "bank_unlinked",
            user_id=str(user_id),
            relationship_pk=str(rel.id),
            alpaca_relationship_id=rel.alpaca_relationship_id,
        )

    @staticmethod
    async def create_transfer(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        relationship_pk: uuid.UUID,
        amount: Decimal,
        direction: str,
    ) -> dict[str, Any]:
        rel = await _load_relationship_for_user(db, user_id, relationship_pk)
        # Local soft-delete short-circuits before any external call.
        if rel.status == ACH_RELATIONSHIP_STATUS_CANCELED:
            raise ConflictError(
                "This bank account has been unlinked.",
                code="RELATIONSHIP_CANCELED",
            )
        brokerage = await _require_active_brokerage(db, user_id)

        # Refresh from Alpaca before gating so we don't block on a stale
        # creation-time status (QUEUED locally → APPROVED at Alpaca is common)
        # or let a stale-APPROVED row through when Alpaca has since canceled.
        await _refresh_statuses_from_alpaca(
            db,
            alpaca=alpaca,
            alpaca_account_id=brokerage.alpaca_account_id,
            relationships=[rel],
        )

        if rel.status == ACH_RELATIONSHIP_STATUS_CANCEL_REQUESTED:
            logger.warning(
                "transfer_blocked_relationship_cancel_requested",
                user_id=str(user_id),
                relationship_pk=str(rel.id),
                alpaca_relationship_id=rel.alpaca_relationship_id,
            )
            raise ConflictError(
                "This bank link was canceled. Please link another account.",
                code="RELATIONSHIP_CANCELED",
                detail={"status": rel.status},
            )
        if rel.status != ACH_RELATIONSHIP_STATUS_APPROVED:
            logger.warning(
                "transfer_blocked_relationship_not_approved",
                user_id=str(user_id),
                relationship_pk=str(rel.id),
                alpaca_relationship_id=rel.alpaca_relationship_id,
                status=rel.status,
            )
            raise ConflictError(
                "This bank is still being verified. Try again in a few minutes.",
                code="RELATIONSHIP_NOT_APPROVED",
                detail={"status": rel.status},
            )

        transfer = await alpaca.create_transfer(
            brokerage.alpaca_account_id,
            relationship_id=rel.alpaca_relationship_id,
            amount=str(amount.quantize(Decimal("0.01"))),
            direction=direction,
        )
        logger.info(
            "transfer_initiated",
            user_id=str(user_id),
            relationship_pk=str(rel.id),
            alpaca_relationship_id=rel.alpaca_relationship_id,
            direction=direction,
            amount=str(amount.quantize(Decimal("0.01"))),
            transfer_id=transfer.get("id"),
            status=transfer.get("status"),
        )
        return transfer

    @staticmethod
    async def list_transfers(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch fresh from Alpaca. Merge local nickname / mask onto each record
        by joining on `alpaca_relationship_id`. Never cache status locally.
        """
        brokerage = await _require_active_brokerage(db, user_id)

        transfers = await alpaca.list_transfers(
            brokerage.alpaca_account_id, limit=limit, offset=offset
        )

        relationships = await AchRelationshipRepository.list_all_for_user(db, user_id)
        bank_by_alpaca_id = {
            r.alpaca_relationship_id: {
                "nickname": r.nickname,
                "account_mask": r.account_mask,
                "institution_name": r.institution_name,
            }
            for r in relationships
        }

        for transfer in transfers:
            transfer["bank"] = bank_by_alpaca_id.get(transfer.get("relationship_id"))
        return transfers

    @staticmethod
    async def cancel_transfer(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
        transfer_id: str,
    ) -> None:
        """Cancel an in-flight ACH transfer.

        Transfers aren't persisted locally, so ownership is enforced by scoping
        the lookup + DELETE to the caller's own Alpaca account — a transfer that
        isn't theirs simply isn't in the list and surfaces as a 404.
        """
        brokerage = await _require_active_brokerage(db, user_id)

        transfers = await alpaca.list_transfers(brokerage.alpaca_account_id)
        target = next((t for t in transfers if t.get("id") == transfer_id), None)
        if target is None:
            raise NotFoundError("Transfer not found")

        transfer_status = target.get("status")
        if transfer_status not in CANCELABLE_TRANSFER_STATUSES:
            logger.info(
                "transfer_cancel_blocked_not_cancelable",
                user_id=str(user_id),
                transfer_id=transfer_id,
                status=transfer_status,
            )
            raise ConflictError(
                "This transfer can no longer be canceled.",
                code="TRANSFER_NOT_CANCELABLE",
                detail={"status": transfer_status},
            )

        try:
            await alpaca.cancel_transfer(brokerage.alpaca_account_id, transfer_id)
        except AlpacaBrokerError as exc:
            if (exc.detail or {}).get("code") == ALPACA_TRANSFER_NOT_CANCELABLE_CODE:
                raise ConflictError(
                    "This transfer can no longer be canceled.",
                    code="TRANSFER_NOT_CANCELABLE",
                ) from exc
            raise

        logger.info(
            "transfer_canceled",
            user_id=str(user_id),
            alpaca_account_id=brokerage.alpaca_account_id,
            transfer_id=transfer_id,
        )


async def _refresh_statuses_from_alpaca(
    db: AsyncSession,
    *,
    alpaca: AlpacaBrokerService,
    alpaca_account_id: str,
    relationships: list[AchRelationship],
) -> None:
    """Refresh local ACH relationship statuses from Alpaca.

    Alpaca has no SSE stream for relationship lifecycle (QUEUED → APPROVED or
    async CANCEL_REQUESTED), so polling on read is the only way to observe
    transitions. Skips local CANCELED rows (soft-delete wins) and rows Alpaca
    has dropped entirely (leave drift for operators).
    """
    non_terminal = [
        r for r in relationships if r.status != ACH_RELATIONSHIP_STATUS_CANCELED
    ]
    if not non_terminal:
        return

    remote_list = await alpaca.list_ach_relationships(alpaca_account_id)
    remote_by_id = {r["id"]: r for r in remote_list}

    changed = False
    for rel in non_terminal:
        remote = remote_by_id.get(rel.alpaca_relationship_id)
        if remote is None:
            continue
        new_status = remote.get("status")
        if new_status and new_status != rel.status:
            logger.info(
                "ach_relationship_status_refreshed",
                relationship_pk=str(rel.id),
                alpaca_relationship_id=rel.alpaca_relationship_id,
                status_from=rel.status,
                status_to=new_status,
            )
            rel.status = new_status
            changed = True

    if changed:
        await db.flush()


async def _compensate_alpaca_ach_relationship(
    *,
    alpaca: AlpacaBrokerService,
    alpaca_account_id: str,
    alpaca_relationship_id: str,
    user_id: uuid.UUID,
) -> None:
    """Best-effort delete of an Alpaca ACH relationship we failed to persist.

    Called from `link_bank`'s final block when the local DB write fails
    (or the race-resolution path picks up another request's row). Keeps our
    DB and Alpaca's state in sync; without this, a DB blip after the Alpaca
    call leaves an orphan that breaks every subsequent retry with
    BANK_ALREADY_LINKED.

    Swallows errors by design. The original exception (if any) is the one
    the caller needs to see; cleanup failure is logged for operator
    reconciliation but must not mask the cause.
    """
    try:
        await alpaca.delete_ach_relationship(
            alpaca_account_id, alpaca_relationship_id
        )
        logger.info(
            "link_bank_alpaca_compensation_succeeded",
            user_id=str(user_id),
            alpaca_relationship_id=alpaca_relationship_id,
        )
    except Exception as cleanup_exc:  # noqa: BLE001 — intentional broad catch
        logger.error(
            "link_bank_alpaca_compensation_failed",
            user_id=str(user_id),
            alpaca_relationship_id=alpaca_relationship_id,
            cleanup_error=str(cleanup_exc),
        )


async def _require_active_brokerage(db: AsyncSession, user_id: uuid.UUID):
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    status = brokerage.account_status if brokerage else None
    if brokerage is None or status != BROKERAGE_ACCOUNT_STATUS_ACTIVE:
        logger.warning(
            "funding_blocked_account_not_active",
            user_id=str(user_id),
            account_status=status,
        )
        raise ConflictError(
            "Your brokerage account is not active yet.",
            code="ACCOUNT_NOT_ACTIVE",
            detail={"account_status": status},
        )
    return brokerage


async def _find_active_relationship_for_item(
    db: AsyncSession, plaid_item_pk: uuid.UUID
) -> AchRelationship | None:
    result = await db.execute(
        select(AchRelationship).where(
            AchRelationship.plaid_item_id == plaid_item_pk,
            AchRelationship.status != ACH_RELATIONSHIP_STATUS_CANCELED,
        )
    )
    return result.scalars().first()


async def _load_relationship_for_user(
    db: AsyncSession, user_id: uuid.UUID, relationship_pk: uuid.UUID
) -> AchRelationship:
    rel = await AchRelationshipRepository.get_by_id(db, relationship_pk)
    if rel is None or rel.user_id != user_id:
        raise NotFoundError("Bank account not found")
    return rel
