"""Custom tool dispatch — lookup → validate → execute → persist → emit.

Server tools are handled in :mod:`app.ai.runtime.dispatch.server`. This
module covers the ``tool_use`` stop-reason path: tools registered in
:class:`~app.ai.runtime.types.ToolRegistry`.

Parallel dispatch is via :func:`asyncio.gather`; the first error in input
order becomes the iteration's terminal error code while sibling tools
still run to completion.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import pydantic
import structlog

from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.types import ToolRegistry
from app.ai.tools.base import ToolContext, ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import BlockEnd, BlockStart, Event
from app.repositories.conversation import ConversationRepository

__all__ = [
    "RecordingEmitter",
    "ToolDispatchOutcome",
    "dispatch_tool_uses",
    "record_tool_execution",
]

logger = structlog.get_logger(__name__)


async def record_tool_execution(
    db_factory: DbSessionFactory,
    /,
    **kwargs: Any,
) -> None:
    """Open one session and write a ``tool_executions`` row.

    Thin wrapper so callers don't repeat the ``async with db_factory()``
    ceremony for every error/success branch.
    """
    async with db_factory() as db:
        await ConversationRepository.record_tool_execution(db, **kwargs)


class RecordingEmitter:
    """Wrap an emitter and record ``BlockStart`` block_ids.

    Lets the tool-result branch tell whether a tool already announced its
    UI block inline.
    """

    def __init__(self, underlying: Any) -> None:
        self._underlying = underlying
        self.started_block_ids: set[str] = set()

    async def emit(self, event: Event) -> None:
        if isinstance(event, BlockStart):
            block_id = event.block.get("block_id")
            if isinstance(block_id, str) and block_id:
                self.started_block_ids.add(block_id)
        await self._underlying.emit(event)


class ToolDispatchOutcome:
    """Aggregated state of one iteration's tool-use processing.

    On any tool failure, the first error in input order is set. Sibling
    tools still run and write their audit rows.
    """

    __slots__ = (
        "terminal_error_code",
        "tool_result_blocks",
        "ui_block_dicts",
        "tool_call_count",
    )

    def __init__(self) -> None:
        self.terminal_error_code: ErrorCode | None = None
        self.tool_result_blocks: list[dict[str, Any]] = []
        self.ui_block_dicts: list[dict[str, Any]] = []
        self.tool_call_count: int = 0


@dataclass(slots=True)
class _PerToolResult:
    # Lookup/validation/execute errors are caught and surfaced via
    # ``error_code``. Programming bugs raise out.

    tool_result_block: dict[str, Any] | None
    ui_block_dict: dict[str, Any] | None
    counted: bool
    error_code: ErrorCode | None


async def _dispatch_one_tool_use(
    *,
    block: Any,
    tool_registry: ToolRegistry,
    user_id: uuid.UUID,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
    invocation_id: uuid.UUID,
) -> _PerToolResult:
    """Lookup → validate → execute → persist → emit wire events.

    Every exit path writes one ``tool_executions`` row.
    """
    tool_name = getattr(block, "name", "") or ""
    tool_use_id = getattr(block, "id", "") or ""
    raw_input = getattr(block, "input", None)
    input_payload = raw_input if isinstance(raw_input, dict) else {}

    # KeyError = Claude called an unregistered tool (wiring bug).
    try:
        tool = tool_registry.get(tool_name)
    except KeyError:
        logger.warning(
            "loop_tool_lookup_failed",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        await record_tool_execution(
            db_factory,
            model_invocation_id=invocation_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            input_payload=input_payload,
            status="error",
            error_message=f"unknown tool: {tool_name}",
        )
        return _PerToolResult(
            tool_result_block=None,
            ui_block_dict=None,
            counted=False,
            error_code=ErrorCode.INTERNAL_ERROR,
        )

    # ``execute`` only ever sees validated input.
    try:
        validated_input = tool.Input.model_validate(raw_input)
    except pydantic.ValidationError as exc:
        await record_tool_execution(
            db_factory,
            model_invocation_id=invocation_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            input_payload=input_payload,
            status="error",
            error_message=str(exc),
        )
        return _PerToolResult(
            tool_result_block=None,
            ui_block_dict=None,
            counted=False,
            error_code=ErrorCode.VALIDATION_ERROR,
        )

    # Per-tool recording emitter — recording stays local, the underlying
    # emitter is shared. Sibling tools' events interleave on the wire.
    recording_emitter = RecordingEmitter(sse_emitter)
    ctx = ToolContext(
        user_id=user_id,
        db_factory=db_factory,
        sse_emitter=recording_emitter,  # type: ignore[arg-type]
        http_clients=http_clients,
    )

    tool_started = time.monotonic()
    try:
        tool_result = await tool.execute(validated_input, ctx)
    except Exception as exc:
        tool_latency_ms = int((time.monotonic() - tool_started) * 1000)
        logger.exception(
            "loop_tool_execute_failed",
            tool_name=tool_name,
            tool_use_id=tool_use_id,
        )
        await record_tool_execution(
            db_factory,
            model_invocation_id=invocation_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            input_payload=input_payload,
            status="error",
            error_message=f"{type(exc).__name__}: {exc}",
            latency_ms=tool_latency_ms,
        )
        # Any exception from a tool is ``TOOL_ERROR``.
        return _PerToolResult(
            tool_result_block=None,
            ui_block_dict=None,
            counted=False,
            error_code=ErrorCode.TOOL_ERROR,
        )
    tool_latency_ms = int((time.monotonic() - tool_started) * 1000)

    # Emit block_start only if the tool didn't already.
    ui_block_dict: dict[str, Any] | None = None
    ui_blocks_emitted_for_row: list[dict[str, Any]] | None = None
    if tool_result.ui_block is not None:
        ui_block_dict = tool_result.ui_block.model_dump(mode="json")
        block_id = ui_block_dict.get("block_id")
        if isinstance(block_id, str) and block_id:
            if block_id not in recording_emitter.started_block_ids:
                await sse_emitter.emit(BlockStart(block=ui_block_dict))
            await sse_emitter.emit(BlockEnd(block_id=block_id))
        ui_blocks_emitted_for_row = [ui_block_dict]

    await record_tool_execution(
        db_factory,
        model_invocation_id=invocation_id,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        input_payload=input_payload,
        status="success",
        output_payload=tool_result.model_payload,
        internal_trace=tool_result.internal_trace,
        ui_blocks_emitted=ui_blocks_emitted_for_row,
        latency_ms=tool_latency_ms,
    )

    # Anthropic's ``tool_result`` content can be a string or a list of
    # text/image blocks — JSON-encode so any shape roundtrips cleanly.
    return _PerToolResult(
        tool_result_block={
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(tool_result.model_payload),
        },
        ui_block_dict=ui_block_dict,
        counted=True,
        error_code=None,
    )


async def dispatch_tool_uses(
    *,
    response_blocks: list[Any],
    tool_registry: ToolRegistry,
    user_id: uuid.UUID,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
    invocation_id: uuid.UUID,
) -> ToolDispatchOutcome:
    """Run every ``tool_use`` block in parallel.

    Results aggregate in input order. Wire events for siblings interleave
    on the wire; iOS correlates by block_id. The first error becomes the
    iteration's ``terminal_error_code``; siblings still run.
    """
    outcome = ToolDispatchOutcome()

    tool_use_blocks = [
        block
        for block in response_blocks
        if getattr(block, "type", None) == "tool_use"
    ]
    if not tool_use_blocks:
        return outcome

    coros = [
        _dispatch_one_tool_use(
            block=block,
            tool_registry=tool_registry,
            user_id=user_id,
            db_factory=db_factory,
            sse_emitter=sse_emitter,
            http_clients=http_clients,
            invocation_id=invocation_id,
        )
        for block in tool_use_blocks
    ]
    # Per-tool coroutines catch their own failures; a raise here is a bug.
    results: list[_PerToolResult] = await asyncio.gather(*coros)

    for result in results:
        if result.error_code is not None and outcome.terminal_error_code is None:
            outcome.terminal_error_code = result.error_code
        if result.ui_block_dict is not None:
            outcome.ui_block_dicts.append(result.ui_block_dict)
        if result.tool_result_block is not None:
            outcome.tool_result_blocks.append(result.tool_result_block)
        if result.counted:
            outcome.tool_call_count += 1

    return outcome
