import redis.asyncio as aioredis

from app.listeners.account_status import AccountStatusListener
from app.listeners.base_sse import BaseSSEListener
from app.listeners.trade_events import TradeEventsListener
from app.listeners.transfer_status import TransferStatusListener
from app.services.alpaca_broker import AlpacaBrokerService


def build_listeners(
    broker: AlpacaBrokerService,
    *,
    redis: aioredis.Redis,
) -> list[BaseSSEListener]:
    """Construct every long-running listener this worker should run.

    Each listener is a :class:`BaseSSEListener` instance the worker spawns
    as an ``asyncio.Task`` in its ``on_startup`` hook.

    ``redis`` is kwarg-only: only ``TransferStatusListener`` consumes it
    today (for cache invalidation), but every listener needs a single seam
    to declare new shared dependencies as they're added.
    """
    return [
        AccountStatusListener(broker),
        TradeEventsListener(broker),
        TransferStatusListener(broker, redis),
    ]
