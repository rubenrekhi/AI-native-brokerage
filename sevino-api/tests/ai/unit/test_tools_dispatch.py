"""Unit tests for ``app.ai.runtime.dispatch.custom.RecordingEmitter``.

The wrapper has a narrow contract: record the ``block_id`` of every
``BlockStart`` it sees, and forward every event verbatim to the
underlying emitter. The dispatch code relies on this dual behavior to
dedup ``BlockStart`` events between the tool's inline emits and the
loop's post-execute emits.

A regression in either direction has real consequences:
* If recording stops, the loop will double-emit ``BlockStart`` for
  tools that already emitted inline (e.g. ``stock_info``'s pill).
* If passthrough drops a ``TextDelta`` / ``BlockData`` / ``BlockEnd``,
  iOS silently loses progress updates from sibling tools.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from app.ai.runtime.dispatch.custom import RecordingEmitter
from app.ai.runtime.errors import ErrorCode
from app.ai.transport.events import (
    BlockData,
    BlockEnd,
    BlockStart,
    Error,
    Event,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)


class _RecordingUnderlying:
    """Underlying emitter stand-in that records every event received.

    Lets tests assert on both the recorded ``block_id`` set (on the
    wrapper) and the verbatim event list (on the underlying).
    """

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class TestRecordingEmitterBlockStart:
    async def test_records_block_id_from_block_start(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        event = BlockStart(
            block={"type": "text", "block_id": "01HXYZ", "text": ""}
        )
        await wrapper.emit(event)

        assert wrapper.started_block_ids == {"01HXYZ"}

    async def test_records_multiple_distinct_block_ids(self) -> None:
        # Each ``BlockStart`` adds to the set. Sibling tools each get
        # their id recorded so the dispatch loop can dedup any one of
        # them independently.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        await wrapper.emit(
            BlockStart(block={"type": "text", "block_id": "a", "text": ""})
        )
        await wrapper.emit(
            BlockStart(block={"type": "text", "block_id": "b", "text": ""})
        )

        assert wrapper.started_block_ids == {"a", "b"}

    async def test_does_not_record_when_block_id_missing(self) -> None:
        # Defensive: a BlockStart with no ``block_id`` key shouldn't
        # poison the set. The set's ``in`` checks downstream rely on
        # truthy string ids.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        await wrapper.emit(BlockStart(block={"type": "text", "text": ""}))

        assert wrapper.started_block_ids == set()

    async def test_does_not_record_empty_block_id(self) -> None:
        # ``isinstance(block_id, str) and block_id`` requires non-empty.
        # An empty string id is treated as "no id" — pin so a regression
        # to ``isinstance(block_id, str)`` alone is caught.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        await wrapper.emit(
            BlockStart(block={"type": "text", "block_id": "", "text": ""})
        )

        assert wrapper.started_block_ids == set()

    async def test_does_not_record_non_string_block_id(self) -> None:
        # Same isinstance guard. An int block_id (shouldn't happen, but
        # defensive) must not crash and must not be recorded.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        await wrapper.emit(
            BlockStart(block={"type": "text", "block_id": 123, "text": ""})
        )

        assert wrapper.started_block_ids == set()

    async def test_duplicate_block_id_absorbed_by_set(self) -> None:
        # A pathological emit that re-uses an id still leaves the set
        # with one entry — set semantics, not list. The dispatch dedup
        # check is membership-based, so duplicates are harmless.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        for _ in range(3):
            await wrapper.emit(
                BlockStart(
                    block={"type": "text", "block_id": "x", "text": ""}
                )
            )

        assert wrapper.started_block_ids == {"x"}


class TestRecordingEmitterPassthrough:
    # Every event type — BlockStart included — must forward verbatim to
    # the underlying. Recording is a side effect, not a replacement for
    # forwarding.

    async def test_forwards_block_start_to_underlying(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = BlockStart(block={"type": "text", "block_id": "a", "text": ""})

        await wrapper.emit(event)

        assert underlying.events == [event]

    async def test_forwards_text_delta_without_recording(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = TextDelta(block_id="a", text="hello")

        await wrapper.emit(event)

        assert underlying.events == [event]
        assert wrapper.started_block_ids == set()

    async def test_forwards_block_data_without_recording(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = BlockData(block_id="a", data={"state": "complete"})

        await wrapper.emit(event)

        assert underlying.events == [event]
        assert wrapper.started_block_ids == set()

    async def test_forwards_block_end_without_recording(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = BlockEnd(block_id="a")

        await wrapper.emit(event)

        assert underlying.events == [event]
        assert wrapper.started_block_ids == set()

    async def test_forwards_turn_started_without_recording(self) -> None:
        # Even events the dispatch code never produces (TurnStarted /
        # TurnCompleted / Error) must round-trip cleanly — the wrapper
        # has no business filtering by event type.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        turn_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        event = TurnStarted(turn_id=turn_id, conversation_id=conv_id)

        await wrapper.emit(event)

        assert underlying.events == [event]
        assert wrapper.started_block_ids == set()

    async def test_forwards_turn_completed_without_recording(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = TurnCompleted(
            turn_id=uuid.uuid4(),
            terminal_state="end_turn",
            total_cost_usd_micros=100,
            iterations_count=1,
        )

        await wrapper.emit(event)

        assert underlying.events == [event]

    async def test_forwards_error_without_recording(self) -> None:
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)
        event = Error(code=ErrorCode.TOOL_ERROR, message="boom")

        await wrapper.emit(event)

        assert underlying.events == [event]

    async def test_passthrough_order_preserved(self) -> None:
        # Multiple events in a sequence must reach the underlying in
        # the same order. iOS's resume decoder relies on wire order.
        underlying = _RecordingUnderlying()
        wrapper = RecordingEmitter(underlying)

        sequence: list[Event] = [
            BlockStart(block={"type": "text", "block_id": "a", "text": ""}),
            TextDelta(block_id="a", text="hel"),
            TextDelta(block_id="a", text="lo"),
            BlockEnd(block_id="a"),
        ]
        for event in sequence:
            await wrapper.emit(event)

        assert underlying.events == sequence

    async def test_awaits_underlying_emit(self) -> None:
        # The wrapper must ``await`` the underlying emit, not call it
        # sync — otherwise SSEEmitter's queue backpressure stops working
        # and the loop could buffer events unboundedly.
        underlying = AsyncMock()
        wrapper = RecordingEmitter(underlying)

        await wrapper.emit(TextDelta(block_id="a", text="x"))

        underlying.emit.assert_awaited_once()
