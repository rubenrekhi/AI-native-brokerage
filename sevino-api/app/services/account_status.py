from datetime import datetime, timezone
from typing import Any

import structlog
from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    SWEEP_STATUS_PENDING_CHANGE,
    BrokerageAccountRepository,
)
from app.repositories.user_profile import UserProfileRepository

logger = structlog.get_logger(__name__)


async def apply_account_status_change(
    session: AsyncSession,
    *,
    alpaca_account_id: str,
    new_status: str,
    kyc_results: dict[str, Any] | None = None,
    event_time: datetime | None = None,
    arq: ArqRedis | None = None,
) -> None:
    """Update one ``brokerage_accounts`` row in response to an Alpaca
    account-lifecycle SSE event.

    Runs inside the caller's transaction — the caller is responsible for
    committing. Shared between the SSE listener (SEV-213) and the
    manual-refresh / KYC-status fallbacks (SEV-211, SEV-212).

    Alpaca's ``/v1/events/accounts/status`` stream fires on any change to
    ``{status, kyc_results, and several other fields we don't track yet}``
    — not only on status transitions. Per the reference page: "Only the
    changed properties are included in the event payload." So the
    idempotence gate below must compare BOTH status and kyc_results —
    short-circuiting on status alone would drop reviewer-amended rejection
    notes that ride on a same-status event (see SEV-213 review discussion).

    ``arq`` is the ARQ job pool. When the account first goes ACTIVE we mark
    the sweep ``PENDING_CHANGE`` and enqueue the background enrollment task
    (SEV-655) instead of PATCHing Alpaca inline — keeping the SSE consumer
    off the Alpaca round-trip. Callers without a pool (manual KYC refresh)
    pass ``None`` and skip enrollment.
    """
    if not new_status:
        return
    account = await BrokerageAccountRepository.get_by_alpaca_account_id(
        session, alpaca_account_id
    )
    if account is None:
        # Alpaca's SSE multiplexes every account on the API key, including
        # ones that don't belong to any Sevino user (partner test accounts,
        # or a race where the event arrives before KYC submission persists).
        # Log and skip — surfacing as an error would page on every such event.
        logger.info(
            "account_status_account_not_found",
            alpaca_account_id=alpaca_account_id,
            new_status=new_status,
        )
        return

    status_changed = account.account_status != new_status
    kyc_changed = (
        kyc_results is not None and account.kyc_results != kyc_results
    )
    if not status_changed and not kyc_changed:
        return

    update_fields: dict[str, Any] = {}
    if kyc_changed:
        update_fields["kyc_results"] = kyc_results
    # Only set activated_at on the *first* transition into ACTIVE — a
    # kyc_results-only event on an already-ACTIVE account must not
    # overwrite the original activation time.
    enqueue_enrollment = False
    if status_changed and new_status == STATUS_ACTIVE:
        activated_at = event_time or datetime.now(timezone.utc)
        update_fields["activated_at"] = activated_at

        # FDIC cash sweep enrollment (SEV-655). Optimistically mark the sweep
        # PENDING_CHANGE and enqueue the background task that PATCHes Alpaca,
        # rather than blocking the SSE consumer on the round-trip. The Alpaca
        # cash_interest SSE event later flips PENDING_CHANGE -> ACTIVE.
        # Config-gated (ships before Alpaca provisions our tier) and arq-gated
        # (manual KYC refresh has no pool and skips enrollment).
        if arq is not None and settings.alpaca_apr_tier_name:
            update_fields["sweep_status"] = SWEEP_STATUS_PENDING_CHANGE
            update_fields["sweep_enrolled_at"] = activated_at
            enqueue_enrollment = True

    previous_status = account.account_status
    await BrokerageAccountRepository.update_status(
        session, account.id, new_status, **update_fields
    )
    # First-time ACTIVE is the authoritative signal that onboarding is truly
    # done (SEV-327) — flip the profile flag in the same transaction. The
    # status_changed guard above makes this idempotent: replays short-circuit
    # before reaching here.
    if status_changed and new_status == STATUS_ACTIVE:
        await UserProfileRepository.update_fields(
            session, account.user_id, onboarding_completed=True
        )
        logger.info(
            "onboarding_completed_flipped",
            user_id=str(account.user_id),
            alpaca_account_id=alpaca_account_id,
        )

    if enqueue_enrollment:
        # Enqueue inside the caller's transaction window so a failed enqueue
        # (Redis down) propagates and rolls back the PENDING_CHANGE write — no
        # stuck status without a job. The reverse is not atomic: a successful
        # enqueue followed by a failed commit leaves a job pointing at a row
        # whose PENDING_CHANGE rolled back. The task re-reads by id and the
        # Alpaca PATCH is idempotent, so it tolerates firing against that row.
        await arq.enqueue_job("enroll_cash_interest", str(account.id))
        logger.info(
            "cash_interest_enroll_enqueued",
            alpaca_account_id=alpaca_account_id,
            user_id=str(account.user_id),
            brokerage_account_id=str(account.id),
        )

    logger.info(
        "account_status_applied",
        alpaca_account_id=alpaca_account_id,
        previous_status=previous_status,
        new_status=new_status,
        kyc_changed=kyc_changed,
    )


async def apply_sweep_status_change(
    session: AsyncSession,
    *,
    alpaca_account_id: str,
    new_status: str,
    event_time: datetime | None = None,
) -> None:
    """Update ``brokerage_accounts.sweep_status`` in response to an Alpaca
    ``cash_interest`` SSE event.

    Runs inside the caller's transaction — the caller is responsible for
    committing. Same shape as ``apply_account_status_change``: idempotent on
    replay, skips silently when the event references an account we don't
    own. ``event_time`` is accepted for symmetry with the sibling helper but
    is not yet persisted — the schema has no sweep-event timestamp column
    distinct from ``sweep_enrolled_at``, which is owned by the enrollment
    request flow rather than this listener.
    """
    if not new_status:
        return
    account = await BrokerageAccountRepository.get_by_alpaca_account_id(
        session, alpaca_account_id
    )
    if account is None:
        logger.info(
            "sweep_status_account_not_found",
            alpaca_account_id=alpaca_account_id,
            new_status=new_status,
        )
        return

    if account.sweep_status == new_status:
        return

    previous = account.sweep_status
    await BrokerageAccountRepository.update_status(
        session,
        account.id,
        sweep_status=new_status,
    )
    logger.info(
        "sweep_status_applied",
        alpaca_account_id=alpaca_account_id,
        previous_sweep_status=previous,
        new_sweep_status=new_status,
    )
