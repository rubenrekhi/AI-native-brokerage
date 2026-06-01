"""ARQ task: enroll an activated brokerage account in the FDIC cash sweep.

Decouples the Alpaca ``PATCH /v1/accounts/{id}`` from the account-status SSE
handler (SEV-655). Two triggers share this one task — the first ACTIVE
transition (``apply_account_status_change``) and the manual re-enroll endpoint
(``POST /v1/brokerage/cash-interest/enroll``) — so both go through the same
retry policy.

On success the task leaves ``sweep_status`` at ``PENDING_CHANGE``: the Alpaca
``cash_interest.USD.status_to=ACTIVE`` SSE event is what flips it to ``ACTIVE``
(via ``apply_sweep_status_change``). The PATCH is idempotent upstream, so
retries and SSE-replay-driven re-runs are safe.
"""

import uuid

import sentry_sdk
import structlog
from arq import Retry

from app.config import settings
from app.database import async_session
from app.repositories.brokerage_account import (
    SWEEP_STATUS_INACTIVE,
    BrokerageAccountRepository,
)
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)

# Total attempts before the account is left INACTIVE for the user to recover
# via the manual re-enroll endpoint. Registered with the same value in
# ``app.worker`` so the final-attempt Sentry capture lines up with ARQ's retry
# budget.
ENROLL_CASH_INTEREST_MAX_TRIES = 3
_RETRY_BACKOFF_BASE_SECONDS = 2


async def enroll_cash_interest(ctx: dict, brokerage_account_id: str) -> None:
    if not settings.alpaca_apr_tier_name:
        logger.warning(
            "cash_interest_enroll_skipped_no_tier",
            brokerage_account_id=brokerage_account_id,
        )
        return

    alpaca: AlpacaBrokerService = ctx["alpaca"]
    async with async_session() as session:
        account = await BrokerageAccountRepository.get_by_id(
            session, uuid.UUID(brokerage_account_id)
        )
        if account is None:
            logger.warning(
                "cash_interest_enroll_account_not_found",
                brokerage_account_id=brokerage_account_id,
            )
            return

        try:
            await alpaca.assign_apr_tier(
                account.alpaca_account_id, settings.alpaca_apr_tier_name
            )
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            account.sweep_status = SWEEP_STATUS_INACTIVE
            await session.commit()

            job_try = ctx.get("job_try", 1)
            status_code = getattr(exc, "status_code", None)
            logger.warning(
                "cash_interest_enroll_failed",
                brokerage_account_id=brokerage_account_id,
                alpaca_account_id=account.alpaca_account_id,
                apr_tier_name=settings.alpaca_apr_tier_name,
                status_code=status_code,
                job_try=job_try,
                exc_type=type(exc).__name__,
            )

            if job_try >= ENROLL_CASH_INTEREST_MAX_TRIES:
                # Retries exhausted: leave the account INACTIVE and surface a
                # single Sentry event (not one per attempt) so ops can find
                # the row. The user recovers via the re-enroll endpoint.
                logger.error(
                    "cash_interest_enroll_abandoned",
                    brokerage_account_id=brokerage_account_id,
                    alpaca_account_id=account.alpaca_account_id,
                    apr_tier_name=settings.alpaca_apr_tier_name,
                    status_code=status_code,
                    job_try=job_try,
                    exc_type=type(exc).__name__,
                )
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("alpaca_account_id", account.alpaca_account_id)
                    scope.set_context(
                        "cash_interest_enrollment",
                        {
                            "brokerage_account_id": brokerage_account_id,
                            "alpaca_account_id": account.alpaca_account_id,
                            "apr_tier_name": settings.alpaca_apr_tier_name,
                            "status_code": status_code,
                            "exc_type": type(exc).__name__,
                        },
                    )
                    sentry_sdk.capture_message(
                        "FDIC sweep enrollment failed after retries; "
                        "account left INACTIVE",
                        level="error",
                    )
                raise

            raise Retry(defer=_RETRY_BACKOFF_BASE_SECONDS * 2 ** (job_try - 1))

        logger.info(
            "cash_interest_enroll_requested",
            brokerage_account_id=brokerage_account_id,
            alpaca_account_id=account.alpaca_account_id,
            apr_tier_name=settings.alpaca_apr_tier_name,
        )
