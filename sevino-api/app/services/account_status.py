from datetime import datetime, timezone
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.repositories.user_profile import UserProfileRepository
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)


async def apply_account_status_change(
    session: AsyncSession,
    *,
    alpaca_account_id: str,
    new_status: str,
    kyc_results: dict[str, Any] | None = None,
    event_time: datetime | None = None,
    alpaca: AlpacaBrokerService | None = None,
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
        activated_at = event_time or datetime.now(timezone.utc)
        update_fields["activated_at"] = activated_at

        # FDIC cash sweep enrollment (SEV-318). Idempotent: PATCHing the
        # same tier twice is a no-op upstream, so SSE replays after a
        # checkpoint stall re-issue safely. Non-blocking: if Alpaca
        # returns an error OR the network is unreachable we still mark
        # the account ACTIVE — the user just doesn't earn interest until
        # we retry. Config-gated so this code can ship before Alpaca
        # provisions our tier.
        if alpaca is not None and settings.alpaca_apr_tier_name:
            try:
                await alpaca.update_account(
                    alpaca_account_id,
                    {
                        "cash_interest": {
                            "USD": {
                                "apr_tier_name": settings.alpaca_apr_tier_name
                            }
                        }
                    },
                )
                update_fields["sweep_status"] = "PENDING_CHANGE"
                update_fields["sweep_enrolled_at"] = activated_at
                logger.info(
                    "sweep_enrollment_requested",
                    alpaca_account_id=alpaca_account_id,
                    user_id=str(account.user_id),
                    apr_tier_name=settings.alpaca_apr_tier_name,
                )
            except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
                status_code = getattr(exc, "status_code", None)
                logger.warning(
                    "sweep_enrollment_failed",
                    alpaca_account_id=alpaca_account_id,
                    user_id=str(account.user_id),
                    apr_tier_name=settings.alpaca_apr_tier_name,
                    status_code=status_code,
                    message=getattr(exc, "message", str(exc)),
                    exc_type=type(exc).__name__,
                )
                # Account is going ACTIVE without sweep — escalate so ops
                # can find the row and either retry or remediate. The SSE
                # listener already opens a scope with sse_stream / event id
                # tags; add account-scoped tags so the event is filterable.
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("alpaca_account_id", alpaca_account_id)
                    scope.set_tag(
                        "sweep_failure_status_code",
                        str(status_code) if status_code is not None else "transport",
                    )
                    scope.set_context(
                        "sweep_enrollment",
                        {
                            "alpaca_account_id": alpaca_account_id,
                            "user_id": str(account.user_id),
                            "apr_tier_name": settings.alpaca_apr_tier_name,
                            "exc_type": type(exc).__name__,
                            "message": getattr(exc, "message", str(exc)),
                        },
                    )
                    sentry_sdk.capture_message(
                        "FDIC sweep enrollment failed; account activated without sweep",
                        level="warning",
                    )
                update_fields["sweep_status"] = "INACTIVE"

    previous_status = account.account_status
    await BrokerageAccountRepository.update_status(
        session, account.id, new_status, **update_fields
    )
    # First-time ACTIVE is the authoritative signal that onboarding is truly
    # done (SEV-327) — flip the profile flag in the same transaction. The
    # status_changed guard above makes this idempotent: replays short-circuit
    # before reaching here.
    if status_changed and new_status == "ACTIVE":
        await UserProfileRepository.update_fields(
            session, account.user_id, onboarding_completed=True
        )
        logger.info(
            "onboarding_completed_flipped",
            user_id=str(account.user_id),
            alpaca_account_id=alpaca_account_id,
        )
    logger.info(
        "account_status_applied",
        alpaca_account_id=alpaca_account_id,
        previous_status=previous_status,
        new_status=new_status,
        kyc_changed=kyc_changed,
    )
