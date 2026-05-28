from datetime import datetime

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_invalidate
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.services.portfolio import PortfolioRange

logger = structlog.get_logger(__name__)


async def handle_transfer_status_change(
    session: AsyncSession,
    redis: aioredis.Redis,
    *,
    alpaca_account_id: str,
    transfer_id: str,
    status_from: str | None,
    status_to: str,
    event_time: datetime | None,
) -> None:
    """Invalidate the affected user's portfolio cache in response to an
    Alpaca transfer-status SSE event.

    Idempotent by construction: cache invalidation is a no-op if the keys
    don't exist, so replays of the same event (after a reconnect with
    ``?since_id=...``) are harmless.

    Caller owns the session lifecycle — this service does not commit.
    ``cache_invalidate`` swallows ``RedisError`` internally; a transient
    Redis blip will not propagate out.
    """
    account = await BrokerageAccountRepository.get_by_alpaca_account_id(
        session, alpaca_account_id
    )
    if account is None:
        # Alpaca's SSE multiplexes every account on the API key, including
        # ones that don't belong to any Sevino user (partner test accounts,
        # other brokerages on the same key). Log and skip — surfacing as
        # warning would page on every such event.
        logger.info(
            "transfer_status_account_not_found",
            alpaca_account_id=alpaca_account_id,
            transfer_id=transfer_id,
        )
        return

    user_id = account.user_id
    keys = [
        f"portfolio:snapshot:{user_id}",
        f"portfolio:holdings:{user_id}",
        # Drive from PortfolioRange so adding a range to the enum forces
        # invalidation to follow — silent miss otherwise.
        *[f"portfolio:history:{user_id}:{r.value}" for r in PortfolioRange],
    ]
    await cache_invalidate(redis, keys)

    logger.info(
        "transfer_status_handled",
        user_id=str(user_id),
        alpaca_account_id=alpaca_account_id,
        transfer_id=transfer_id,
        status_from=status_from or None,
        status_to=status_to,
        event_time=event_time.isoformat() if event_time else None,
    )
