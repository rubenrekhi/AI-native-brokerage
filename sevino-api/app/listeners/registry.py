from app.listeners.account_status import AccountStatusListener
from app.listeners.base_sse import BaseSSEListener
from app.listeners.trade_events import TradeEventsListener
from app.services.alpaca_broker import AlpacaBrokerService


def build_listeners(broker: AlpacaBrokerService) -> list[BaseSSEListener]:
    """Construct every long-running listener this worker should run.

    Each listener is a :class:`BaseSSEListener` instance the worker spawns
    as an ``asyncio.Task`` in its ``on_startup`` hook.
    """
    return [
        AccountStatusListener(broker),
        TradeEventsListener(broker),
    ]
