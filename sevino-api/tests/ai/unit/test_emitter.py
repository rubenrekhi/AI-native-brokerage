"""Unit tests for ``app/ai/transport/emitter.py`` (AI v0 plan B2.2).

Cover the three acceptance criteria:

1. Spawn a coroutine that emits 3 events, consume via ``async for`` —
   receives all 3 in order.
2. ``close()`` ends the iterator cleanly.
3. Backpressure handled (queue size config).
"""

from __future__ import annotations

import asyncio

import pytest

from app.ai.transport.emitter import DEFAULT_QUEUE_SIZE, SSEEmitter
from app.ai.transport.events import Status, TextDelta


class TestEmitAndIterate:
    async def test_three_events_consumed_in_order(self):
        # Acceptance criterion 1 — the canonical happy path.
        emitter = SSEEmitter()
        events = [Status(label=f"step {i}") for i in range(3)]

        async def produce() -> None:
            for event in events:
                await emitter.emit(event)
            await emitter.close()

        producer = asyncio.create_task(produce())
        received = [event async for event in emitter.iter_events()]
        await producer

        assert received == events

    async def test_iterator_yields_concurrent_emissions_in_order(self):
        # Producer and consumer running concurrently — the queue's FIFO
        # discipline must preserve the emit order even under interleaving.
        emitter = SSEEmitter()
        emitted: list[Status] = []
        received: list[Status] = []

        async def produce() -> None:
            for i in range(20):
                event = Status(label=f"s{i}")
                emitted.append(event)
                await emitter.emit(event)
                # Yield to the scheduler so the consumer interleaves.
                await asyncio.sleep(0)
            await emitter.close()

        async def consume() -> None:
            async for event in emitter.iter_events():
                received.append(event)

        await asyncio.gather(produce(), consume())
        assert received == emitted


class TestClose:
    async def test_close_ends_iterator(self):
        # Acceptance criterion 2 — close on an empty queue ends the
        # iterator without yielding anything.
        emitter = SSEEmitter()
        await emitter.close()
        received = [event async for event in emitter.iter_events()]
        assert received == []

    async def test_close_drains_pending_events_first(self):
        # Events emitted before close must reach the consumer; close is
        # a clean shutdown, not an abort.
        emitter = SSEEmitter()
        events = [Status(label=f"s{i}") for i in range(5)]
        for event in events:
            await emitter.emit(event)
        await emitter.close()

        received = [event async for event in emitter.iter_events()]
        assert received == events

    async def test_close_is_idempotent(self):
        # Repeated close() must be a no-op so cleanup paths (try/finally,
        # cancellation handlers) can call it without checking state.
        emitter = SSEEmitter()
        await emitter.close()
        await emitter.close()
        await emitter.close()

        received = [event async for event in emitter.iter_events()]
        assert received == []

    async def test_emit_after_close_raises(self):
        # Emitting on a closed emitter is a producer-side bug — surface
        # it loudly rather than silently dropping the event.
        emitter = SSEEmitter()
        await emitter.close()
        with pytest.raises(RuntimeError, match="closed"):
            await emitter.emit(Status(label="late"))

    async def test_close_unblocks_a_waiting_consumer(self):
        # The consumer is parked on `await self._queue.get()`; close must
        # wake it up so the iterator returns. Without this, a chat-turn
        # endpoint whose loop closed cleanly would hang the response.
        emitter = SSEEmitter()

        async def consumer() -> list[Status]:
            return [event async for event in emitter.iter_events()]

        consumer_task = asyncio.create_task(consumer())
        # Let the consumer reach the queue.get() suspend point.
        await asyncio.sleep(0)
        await emitter.close()
        result = await asyncio.wait_for(consumer_task, timeout=1.0)
        assert result == []


class TestBackpressure:
    async def test_default_queue_size(self):
        # Lock the documented default — the loop and route both rely on
        # this constant via the public name.
        assert DEFAULT_QUEUE_SIZE == 64

    async def test_queue_size_is_configurable(self):
        # Acceptance criterion 3 (config) — tests use a small queue to
        # exercise backpressure deterministically; production may tune
        # higher for slow consumers.
        emitter = SSEEmitter(queue_size=2)
        assert emitter._queue.maxsize == 2

    async def test_emit_blocks_when_queue_is_full(self):
        # Acceptance criterion 3 (behavior) — with a maxsize=1 queue and
        # no consumer reading, the second emit must block until space
        # frees up, applying backpressure to the producer.
        emitter = SSEEmitter(queue_size=1)
        await emitter.emit(TextDelta(block_id="b1", text="first"))

        # Second emit blocks because the queue is full.
        emit_task = asyncio.create_task(
            emitter.emit(TextDelta(block_id="b1", text="second"))
        )
        # Let the scheduler run; the task should still be pending.
        await asyncio.sleep(0.01)
        assert not emit_task.done()

        # Drain one item — that frees a slot and the blocked emit completes.
        async def consume_one() -> TextDelta:
            agen = emitter.iter_events()
            return await agen.__anext__()

        first = await consume_one()
        assert first.text == "first"
        await asyncio.wait_for(emit_task, timeout=1.0)

    async def test_no_backpressure_within_queue_capacity(self):
        # Inverse of the previous test: emits up to maxsize must not
        # block, so a producer ahead of the consumer doesn't pay
        # latency on every event in the common case.
        emitter = SSEEmitter(queue_size=4)
        # All four emits should complete without a consumer.
        for i in range(4):
            await asyncio.wait_for(
                emitter.emit(TextDelta(block_id="b1", text=f"d{i}")),
                timeout=0.1,
            )
