from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.brokerage_account import BrokerageAccountRepository

logger = structlog.get_logger(__name__)


async def apply_account_status_change(
    session: AsyncSession,
    *,
    alpaca_account_id: str,
    new_status: str,
    kyc_results: dict[str, Any] | None = None,
    event_time: datetime | None = None,
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
    """
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
    if status_changed and new_status == "ACTIVE":
        update_fields["activated_at"] = event_time or datetime.now(timezone.utc)
        # TODO(SEV-318): trigger FDIC insured cash sweep enrollment here.

    await BrokerageAccountRepository.update_status(
        session, account.id, new_status, **update_fields
    )
    logger.info(
        "account_status_applied",
        alpaca_account_id=alpaca_account_id,
        previous_status=account.account_status,
        new_status=new_status,
        kyc_changed=kyc_changed,
    )
