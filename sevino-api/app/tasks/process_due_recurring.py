"""Daily cron that executes due recurring investments (PRD 11.6).

Runs before the US open; Alpaca queues the market-day orders to the open. If
any plan hit a transient upstream error, re-runs shortly (bounded by
max_tries) so a rate-limit blip doesn't defer a buy a full day — already-
processed plans are skipped on the re-run.
"""

from datetime import datetime, timezone

import sentry_sdk
import structlog
from arq import Retry

from app.config import settings
from app.database import async_session
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.recurring_engine import run_due_recurring_investments

logger = structlog.get_logger(__name__)

PROCESS_DUE_RECURRING_MAX_TRIES = 3
_RETRY_DEFER_SECONDS = 60


async def process_due_recurring(ctx: dict) -> dict:
    if settings.is_pr_preview:
        logger.debug(
            "recurring_run_skipped_pr_preview",
            railway_env=settings.railway_environment_name,
        )
        return {"status": "skipped", "reason": "pr-preview"}

    alpaca: AlpacaBrokerService = ctx["alpaca"]
    as_of = datetime.now(timezone.utc).date()

    async with async_session() as session:
        summary = await run_due_recurring_investments(
            session, alpaca=alpaca, as_of=as_of
        )
        await session.commit()

    if summary.get("transient", 0) > 0:
        if ctx.get("job_try", 1) >= PROCESS_DUE_RECURRING_MAX_TRIES:
            # Retry budget exhausted — a sustained upstream outage is deferring
            # buys. Surface it rather than failing silently; the un-run plans
            # stay due for the next daily tick.
            sentry_sdk.capture_message(
                f"recurring engine exhausted retries with "
                f"{summary['transient']} transient failure(s) on "
                f"{as_of.isoformat()}",
                level="warning",
            )
            return summary
        raise Retry(defer=_RETRY_DEFER_SECONDS)

    return summary
