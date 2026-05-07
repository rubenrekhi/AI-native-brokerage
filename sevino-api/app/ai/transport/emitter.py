"""SSE emitter — producer/consumer queue for an agent turn's event stream.

Per AI v0 plan B2.2 (sevino-api/docs/ai-v0-plan.md). Decouples the agent
loop (which produces SSE events) from the FastAPI route (which streams
them to the client) so:

* The loop is testable without spinning up an HTTP request — a unit test
  hands it an emitter and asserts on the events that come out.
* Future sub-agents (post-v0 multi-agent) inherit the parent's emitter
  and contribute events into the same stream without needing a handle on
  the response object.

Single-producer / single-consumer over an ``asyncio.Queue``. ``close()``
puts a sentinel on the queue that ends the iterator cleanly after any
queued events drain. The queue's ``maxsize`` is the backpressure knob:
when the consumer (the SSE response, ultimately the iOS client) lags,
``emit`` blocks rather than letting the producer build an unbounded
backlog in memory.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.ai.transport.events import Event

__all__ = ["DEFAULT_QUEUE_SIZE", "SSEEmitter"]


# Sized so a fast-emitting loop (Anthropic streams ~50 deltas/s on a
# long response) can buffer roughly a second of work before backpressure
# kicks in. Tunable per emitter for tests and for slow consumers.
DEFAULT_QUEUE_SIZE = 64


class SSEEmitter:
    """Producer/consumer queue between an agent turn and an SSE response.

    The producer (agent loop, plus any sub-agents that share this
    emitter) calls :meth:`emit` for each event. The consumer (the route
    handler) reads with ``async for event in emitter.iter_events()``,
    typically by handing the iterator to ``EventSourceResponse``.
    :meth:`close` ends the iterator once the producer is done.
    """

    def __init__(self, *, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        # Bounded queue is the backpressure mechanism — see module
        # docstring. ``None`` is reserved as the close sentinel; events
        # are Pydantic models so a real event is never ``None``.
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(
            maxsize=queue_size
        )
        self._closed = False

    async def emit(self, event: Event) -> None:
        """Push ``event`` onto the queue, blocking when full.

        Raises ``RuntimeError`` if the emitter has already been closed
        — emitting after close is a producer-side bug (the loop would
        be outliving the response it was meant to feed, and the event
        would silently disappear).
        """
        if self._closed:
            raise RuntimeError("cannot emit on a closed SSEEmitter")
        await self._queue.put(event)

    async def iter_events(self) -> AsyncIterator[Event]:
        """Yield events until the emitter is closed.

        Events emitted before :meth:`close` was called are drained
        first; the iterator only terminates after the close sentinel
        is dequeued. Single-consumer — the queue's items are taken at
        most once, so a second iterator would see no events.
        """
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        """End the iterator after pending events drain.

        Idempotent — repeated calls are no-ops. Async because the close
        sentinel rides on the same queue as events and is therefore
        subject to the same backpressure; this keeps the close-during-
        emit interleaving well-defined (the sentinel is the *last* thing
        the consumer sees).
        """
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)
