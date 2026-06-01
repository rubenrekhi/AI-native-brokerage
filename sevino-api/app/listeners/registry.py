import redis.asyncio as aioredis
from arq.connections import ArqRedis

from app.listeners.account_status import AccountStatusListener
from app.listeners.base_sse import BaseSSEListener
from app.listeners.trade_events import TradeEventsListener
from app.listeners.transfer_status import TransferStatusListener
from app.services.alpaca_broker import AlpacaBrokerService


def build_listeners(
    broker: AlpacaBrokerService,
    *,
    redis: aioredis.Redis,
    arq: ArqRedis | None = None,
) -> list[BaseSSEListener]:
    """Construct every long-running listener this worker should run.

    Each listener is a :class:`BaseSSEListener` instance the worker spawns
    as an ``asyncio.Task`` in its ``on_startup`` hook.

    ``redis`` is kwarg-only: only ``TransferStatusListener`` consumes it
    today (for cache invalidation). ``arq`` is the ArqRedis job pool the
    ``AccountStatusListener`` enqueues the FDIC sweep enrollment task onto
    (SEV-655); kwarg-only and optional so non-worker call sites (tests) can
    omit it.
    """
    return [
        AccountStatusListener(broker, arq=arq),
        TradeEventsListener(broker),
        TransferStatusListener(broker, redis),
    ]
