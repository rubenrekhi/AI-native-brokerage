"""SSE emitter — bounded queue between the agent loop and the SSE response."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.ai.transport.events import Event

__all__ = ["DEFAULT_QUEUE_SIZE", "SSEEmitter"]


# Holds ~1s of work at Anthropic's ~50 deltas/s before backpressure kicks in.
DEFAULT_QUEUE_SIZE = 64


class SSEEmitter:
    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        # ``None`` is the close sentinel; real events are never None.
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(
            maxsize=queue_size
        )
        self._closed = False

    async def emit(self, event: Event) -> None:
        if self._closed:
            raise RuntimeError("cannot emit on a closed SSEEmitter")
        await self._queue.put(event)

    async def iter_events(self) -> AsyncIterator[Event]:
        # Single-consumer — a second iterator would see no events.
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        # Async + queue-bound sentinel so close-during-emit stays
        # well-defined: the sentinel is the last thing the consumer sees.
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)
