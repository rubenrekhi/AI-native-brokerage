"""Unit tests for ``app.ai.runtime.flow.stream_consumer.StreamConsumer``.

Focused on the documented coverage gap: the disconnect-check counter
increments for *both* text deltas and thinking deltas, despite being
named ``_text_deltas_seen``. The cadence is critical — a thinking-heavy
turn polls disconnect on a different real-time rhythm than a text-heavy
turn, and a regression that decouples the counter from one delta type
would silently change the latency of cancel detection.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.ai.runtime.dispatch.server import ServerToolTracker
from app.ai.runtime.flow.stream_consumer import StreamConsumer
from app.ai.runtime.types import DISABLED_SERVER_TOOLS


def _make_consumer(disconnect_check: Any) -> StreamConsumer:
    return StreamConsumer(
        sse_emitter=AsyncMock(),
        server_tool_tracker=ServerToolTracker(),
        server_tools_config=DISABLED_SERVER_TOOLS,
        disconnect_check=disconnect_check,
    )


def _text_delta(index: int, text: str = "x") -> Any:
    return SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def _thinking_delta(index: int, thinking: str = "y") -> Any:
    return SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=SimpleNamespace(type="thinking_delta", thinking=thinking),
    )


class TestDisconnectCheckCadence:
    # ``_DISCONNECT_CHECK_DELTA_INTERVAL = 16``. The counter increments
    # once per delta and only polls disconnect on multiples of 16.

    async def test_no_disconnect_check_polled_under_threshold(self) -> None:
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""

        for _ in range(15):
            await consumer._handle_chunk(_text_delta(0))

        check.assert_not_awaited()

    async def test_disconnect_check_polled_at_16th_text_delta(self) -> None:
        # Exactly at the 16-delta boundary the poll fires once.
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""

        for _ in range(16):
            await consumer._handle_chunk(_text_delta(0))

        check.assert_awaited_once()

    async def test_thinking_delta_advances_the_counter(self) -> None:
        # The variable name says "text_deltas" but the counter also
        # ticks on ``thinking_delta`` — this is the documented gap that
        # makes thinking-heavy turns poll disconnect on a different
        # real-time rhythm than text-heavy turns. Pin the contract so a
        # future split into separate counters is intentional.
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        consumer.open_thinking_blocks[0] = "block-t"

        for _ in range(16):
            await consumer._handle_chunk(_thinking_delta(0))

        check.assert_awaited_once()

    async def test_mixed_deltas_share_one_counter(self) -> None:
        # 8 text + 8 thinking = 16 → exactly one poll. If the counters
        # were split per-type, neither would reach 16 and the poll
        # would never fire.
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""
        consumer.open_thinking_blocks[1] = "block-t"

        for _ in range(8):
            await consumer._handle_chunk(_text_delta(0))
        for _ in range(8):
            await consumer._handle_chunk(_thinking_delta(1))

        check.assert_awaited_once()

    async def test_polls_every_sixteenth_delta(self) -> None:
        # 48 deltas → polls at 16, 32, 48.
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""

        for _ in range(48):
            await consumer._handle_chunk(_text_delta(0))

        assert check.await_count == 3

    async def test_disconnect_check_none_skips_poll_entirely(self) -> None:
        # When the caller didn't wire a disconnect check, the early
        # return must skip the counter entirely — otherwise a 16-delta
        # turn would crash on the ``None`` callable.
        consumer = _make_consumer(None)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""

        # Should not raise. We don't have a check to assert against,
        # so the absence of exception is the contract.
        for _ in range(48):
            await consumer._handle_chunk(_text_delta(0))

    async def test_disconnect_check_true_raises_cancelled(self) -> None:
        # When the poll fires and the check returns True, the consumer
        # raises ``CancelledError`` from the delta-handler — surfacing
        # through ``consume`` so the caller can flush partials.
        check = AsyncMock(return_value=True)
        consumer = _make_consumer(check)
        consumer.open_text_blocks[0] = "block-a"
        consumer.accumulated_text[0] = ""

        # First 15 deltas: no check.
        for _ in range(15):
            await consumer._handle_chunk(_text_delta(0))

        # 16th delta: poll fires, returns True → CancelledError.
        with pytest.raises(asyncio.CancelledError):
            await consumer._handle_chunk(_text_delta(0))

    async def test_unopened_block_delta_does_not_advance_counter(self) -> None:
        # A ``text_delta`` for a block whose ``content_block_start`` was
        # never seen is silently dropped — the counter must NOT
        # advance. Otherwise a malformed stream could spuriously trip
        # the disconnect poll.
        check = AsyncMock(return_value=False)
        consumer = _make_consumer(check)
        # Note: open_text_blocks[0] NOT set.

        for _ in range(20):
            await consumer._handle_chunk(_text_delta(0))

        check.assert_not_awaited()
        assert consumer._text_deltas_seen == 0
