"""Consume Anthropic's streamed messages and forward to SSE.

A :class:`StreamConsumer` is created per iteration. It owns the
stream-time state (``open_text_blocks``, ``open_thinking_blocks``,
``accumulated_text``) and delegates server-tool concerns to a shared
:class:`~app.ai.runtime.server_tools.ServerToolTracker` so the pill state
survives across iterations.

Wire shapes the consumer produces::

    text:              block_start → text_delta* → block_end
    thinking:          block_start(streaming) → text_delta* → block_data(complete) → block_end
    redacted_thinking: block_start(redacted, complete) → block_end

On :class:`asyncio.CancelledError` the consumer closes the upstream
stream eagerly and re-raises with its partial state intact — the caller
flushes any ``accumulated_text`` into the assistant message before the
final DB write.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from anthropic import AsyncAnthropic
from anthropic.types import Message
from ulid import ULID

from app.ai.runtime.server_tools import (
    SERVER_TOOL_RESULT_BLOCK_TYPES,
    ServerToolTracker,
)
from app.ai.runtime.types import ServerToolsConfig
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import BlockData, BlockEnd, BlockStart, TextDelta

__all__ = ["StreamConsumer"]

# Polled every Nth text_delta; lands a CancelledError within a few hundred
# ms of an iOS disconnect at Anthropic's ~50 deltas/s.
_DISCONNECT_CHECK_DELTA_INTERVAL = 16


class StreamConsumer:
    def __init__(
        self,
        *,
        sse_emitter: SSEEmitter,
        server_tool_tracker: ServerToolTracker,
        server_tools_config: ServerToolsConfig,
        disconnect_check: Callable[[], Awaitable[bool]] | None,
    ) -> None:
        self._sse_emitter = sse_emitter
        self._tracker = server_tool_tracker
        self._server_tools_enabled = server_tools_config.any_enabled
        self._disconnect_check = disconnect_check

        self.open_text_blocks: dict[int, str] = {}
        self.open_thinking_blocks: dict[int, str] = {}
        # On mid-stream cancel ``get_final_message`` never returns, so this
        # is the only record of what reached the wire.
        self.accumulated_text: dict[int, str] = {}
        self._text_deltas_seen = 0

    async def consume(
        self,
        anthropic_client: AsyncAnthropic,
        create_kwargs: dict[str, Any],
    ) -> Message:
        async with anthropic_client.messages.stream(**create_kwargs) as stream:
            try:
                async for chunk in stream:
                    await self._handle_chunk(chunk)
                return await stream.get_final_message()
            except asyncio.CancelledError:
                # Close upstream eagerly so the connection is released
                # before the outer finally hits the DB.
                await stream.close()
                raise

    async def _handle_chunk(self, chunk: Any) -> None:
        if chunk.type == "content_block_start":
            await self._on_block_start(chunk)
        elif chunk.type == "content_block_delta":
            await self._on_block_delta(chunk)
        elif chunk.type == "content_block_stop":
            await self._on_block_stop(chunk)

    async def _on_block_start(self, chunk: Any) -> None:
        cb_type = chunk.content_block.type
        if cb_type == "text":
            block_id = str(ULID())
            self.open_text_blocks[chunk.index] = block_id
            self.accumulated_text[chunk.index] = ""
            await self._sse_emitter.emit(
                BlockStart(
                    block={"type": "text", "block_id": block_id, "text": ""}
                )
            )
        elif cb_type == "thinking":
            block_id = str(ULID())
            self.open_thinking_blocks[chunk.index] = block_id
            await self._sse_emitter.emit(
                BlockStart(
                    block={
                        "type": "thinking",
                        "block_id": block_id,
                        "text": "",
                        "redacted": False,
                        "state": "streaming",
                    }
                )
            )
        elif cb_type == "redacted_thinking":
            # Skip ``open_thinking_blocks`` so the delta/stop branches
            # stay no-ops — encrypted payload, no deltas.
            block_id = str(ULID())
            await self._sse_emitter.emit(
                BlockStart(
                    block={
                        "type": "thinking",
                        "block_id": block_id,
                        "text": "",
                        "redacted": True,
                        "state": "complete",
                    }
                )
            )
            await self._sse_emitter.emit(BlockEnd(block_id=block_id))
        elif self._server_tools_enabled and cb_type == "server_tool_use":
            tool_use_id = getattr(chunk.content_block, "id", None)
            raw_name = getattr(chunk.content_block, "name", None)
            if isinstance(tool_use_id, str) and tool_use_id:
                await self._tracker.on_use_started(
                    tool_use_id=tool_use_id,
                    raw_name=raw_name,
                    sse_emitter=self._sse_emitter,
                )
        elif (
            self._server_tools_enabled
            and cb_type in SERVER_TOOL_RESULT_BLOCK_TYPES
        ):
            tool_use_id = getattr(chunk.content_block, "tool_use_id", None)
            if isinstance(tool_use_id, str) and tool_use_id:
                await self._tracker.on_result_received(
                    tool_use_id=tool_use_id,
                    result_block=chunk.content_block,
                    sse_emitter=self._sse_emitter,
                )

    async def _on_block_delta(self, chunk: Any) -> None:
        if (
            chunk.delta.type == "text_delta"
            and chunk.index in self.open_text_blocks
        ):
            self.accumulated_text[chunk.index] += chunk.delta.text
            await self._sse_emitter.emit(
                TextDelta(
                    block_id=self.open_text_blocks[chunk.index],
                    text=chunk.delta.text,
                )
            )
            await self._poll_disconnect()
        elif (
            chunk.delta.type == "thinking_delta"
            and chunk.index in self.open_thinking_blocks
        ):
            await self._sse_emitter.emit(
                TextDelta(
                    block_id=self.open_thinking_blocks[chunk.index],
                    text=chunk.delta.thinking,
                )
            )
            await self._poll_disconnect()

    async def _on_block_stop(self, chunk: Any) -> None:
        block_id = self.open_text_blocks.get(chunk.index)
        if block_id is not None:
            await self._sse_emitter.emit(BlockEnd(block_id=block_id))
            return
        thinking_block_id = self.open_thinking_blocks.get(chunk.index)
        if thinking_block_id is not None:
            await self._sse_emitter.emit(
                BlockData(
                    block_id=thinking_block_id, data={"state": "complete"}
                )
            )
            await self._sse_emitter.emit(BlockEnd(block_id=thinking_block_id))

    async def _poll_disconnect(self) -> None:
        if self._disconnect_check is None:
            return
        self._text_deltas_seen += 1
        if self._text_deltas_seen % _DISCONNECT_CHECK_DELTA_INTERVAL != 0:
            return
        # Poll on cadence so iOS close lands within a few hundred ms.
        if await self._disconnect_check():
            raise asyncio.CancelledError
