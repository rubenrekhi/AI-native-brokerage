from app.listeners.base_sse import BaseSSEListener
from app.services.alpaca_broker import AlpacaBrokerService


def build_listeners(broker: AlpacaBrokerService) -> list[BaseSSEListener]:
    """Construct every long-running listener this worker should run.

    Each listener is a :class:`BaseSSEListener` (or future WebSocket listener)
    instance the worker spawns as an ``asyncio.Task`` in its ``on_startup``
    hook. Returning an empty list is a valid no-op — concrete listeners arrive
    in SEV-213 / SEV-214 / SEV-215 / SEV-216.
    """
    del broker  # unused until SEV-213+
    return []
