"""Agent loop — runs one turn end-to-end.

Extended thinking is always enabled (1024-token budget). The loop iterates
on ``stop_reason == "pause_turn"``; prior thinking blocks are appended to
``messages`` before each call so signatures roundtrip byte-for-byte.

No FastAPI imports — collaborators are passed in so the same function
runs in sub-agents and unit tests.

Each write opens a fresh ``AsyncSession`` so audit rows are durable
mid-turn, not batched at the end.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pydantic
import sentry_sdk
import structlog
from anthropic import AsyncAnthropic
from langfuse import propagate_attributes
from ulid import ULID

from app.ai.observability.langfuse import LangfuseClient
from app.ai.prompts import SystemPrompt
from app.ai.runtime.anthropic_io import scrub_blocks
from app.ai.runtime.caps import CapBreach, HardCaps, check_caps
from app.ai.runtime.cost import cost_usd_micros
from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.errors import ErrorCode, to_error_code
from app.ai.runtime.types import (
    DISABLED_SERVER_TOOLS,
    AgentTurnResult,
    LoopState,
    ModelConfig,
    ServerToolsConfig,
    ToolRegistry,
)
from app.ai.tools.base import ToolContext, ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
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
from app.repositories.conversation import ConversationRepository

logger = structlog.get_logger(__name__)

# TIMEOUT folds into INTERNAL_ERROR — no clean ErrorCode counterpart.
_BREACH_TO_ERROR_CODE: dict[CapBreach, ErrorCode] = {
    CapBreach.ITERATION_LIMIT: ErrorCode.TURN_ITERATION_LIMIT,
    CapBreach.TOOL_CALL_LIMIT: ErrorCode.TOOL_CALL_LIMIT,
    CapBreach.OUTPUT_TOKEN_LIMIT: ErrorCode.OUTPUT_TOKEN_LIMIT,
    CapBreach.TIMEOUT: ErrorCode.INTERNAL_ERROR,
}

# Anthropic requires ``budget_tokens >= 1024`` and ``< max_tokens``.
_THINKING_BUDGET_TOKENS = 1024

# Heuristic for the ``thinking_tokens`` audit column — Anthropic gives no
# per-block breakdown. Redacted blocks contribute zero.
_CHARS_PER_TOKEN = 4

# Polled every Nth text_delta; lands a CancelledError within a few hundred
# ms of an iOS disconnect at Anthropic's ~50 deltas/s.
_DISCONNECT_CHECK_DELTA_INTERVAL = 16

_DEFAULT_CANCELLATION_REASON = "client_disconnect"

_ANTHROPIC_SERVER_TOOL_PREFIX = "anthropic:"

_SERVER_TOOL_RESULT_BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "web_search_tool_result",
        "web_fetch_tool_result",
        "code_execution_tool_result",
    }
)

_SERVER_TOOL_STATUS_LABELS: dict[str, str] = {
    "web_search": "Searching the web",
    "web_fetch": "Fetching webpage",
    "code_execution": "Running code",
}


def _server_tool_status_label(name: str | None) -> str:
    if not isinstance(name, str) or not name:
        return "Using tool"
    if name not in _SERVER_TOOL_STATUS_LABELS:
        # Unknown server tool — fall back but log so we notice.
        logger.warning("loop_unknown_server_tool_label", name=name)
    return _SERVER_TOOL_STATUS_LABELS.get(name, f"Using {name}")


def _result_block_status_state(result_block: Any) -> str:
    content = getattr(result_block, "content", None)
    content_type = (
        getattr(content, "type", None) if content is not None else None
    )
    if isinstance(content_type, str) and content_type.endswith("_error"):
        return "failed"
    return "complete"


def _build_server_tool_specs(
    config: ServerToolsConfig,
) -> list[dict[str, Any]]:
    # ``type`` is Anthropic's date-suffixed version pin. Bumping it opts
    # into behavior changes — coordinate with the matching SDK Param type.
    specs: list[dict[str, Any]] = []
    if config.web_search_enabled:
        specs.append(
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": config.web_search_max_uses,
            }
        )
    if config.web_fetch_enabled:
        specs.append(
            {
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": config.web_fetch_max_uses,
            }
        )
    if config.code_execution_enabled:
        specs.append(
            {
                "type": "code_execution_20250825",
                "name": "code_execution",
            }
        )
    return specs


def _append_status_blocks_for_persistence(
    *,
    tool_use_ids: list[str],
    status_block_records: dict[str, dict[str, Any]],
    status_blocks_persisted: set[str],
    assistant_blocks: list[dict[str, Any]],
) -> None:
    """Append unpersisted status-pill records to ``assistant_blocks``.

    Dedups against ``status_blocks_persisted`` so multi-iteration tool use
    isn't appended twice.
    """
    for tool_use_id in tool_use_ids:
        if tool_use_id in status_blocks_persisted:
            continue
        record = status_block_records.get(tool_use_id)
        if record is None:
            continue
        assistant_blocks.append(record)
        status_blocks_persisted.add(tool_use_id)


def _truncate_for_audit(value: Any, max_chars: int = 2000) -> Any:
    """Clip oversize payloads for the audit row.

    ``_preview`` is debug-only, never JSON-parsed downstream.
    """
    try:
        encoded = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"_audit_error": "non_json_payload"}
    if len(encoded) <= max_chars:
        return value
    return {"_truncated": True, "_preview": encoded[:max_chars]}


async def _record_server_tool_executions(
    *,
    response_blocks: list[Any],
    pending_uses: dict[str, dict[str, Any]],
    invocation_id: uuid.UUID,
    db_factory: DbSessionFactory,
    turn_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    """Pair server-tool uses with their results across iterations.

    Anthropic may emit the use in one iteration and its result in the next.
    Orphans left at turn end are flushed by
    :func:`_flush_orphan_server_tool_uses`.
    """
    if not response_blocks:
        return

    for block in response_blocks:
        if getattr(block, "type", None) != "server_tool_use":
            continue
        tool_use_id = getattr(block, "id", "") or ""
        raw_name = getattr(block, "name", "") or ""
        if not tool_use_id or tool_use_id in pending_uses:
            continue
        raw_input = getattr(block, "input", None)
        pending_uses[tool_use_id] = {
            "tool_name": f"{_ANTHROPIC_SERVER_TOOL_PREFIX}{raw_name}",
            "input_payload": raw_input if isinstance(raw_input, dict) else {},
        }

    for block in response_blocks:
        block_type = getattr(block, "type", None)
        if block_type not in _SERVER_TOOL_RESULT_BLOCK_TYPES:
            continue
        tool_use_id = getattr(block, "tool_use_id", None)
        if not isinstance(tool_use_id, str) or not tool_use_id:
            continue
        use_info = pending_uses.pop(tool_use_id, None)
        if use_info is None:
            logger.warning(
                "loop_server_tool_orphan_result",
                tool_use_id=tool_use_id,
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("turn_id", str(turn_id))
                scope.set_tag("conversation_id", str(conversation_id))
                scope.set_tag("tool_use_id", tool_use_id)
                sentry_sdk.capture_message(
                    "loop_server_tool_orphan_result",
                    level="warning",
                )
            continue

        content = getattr(block, "content", None)
        content_type = (
            getattr(content, "type", None) if content is not None else None
        )
        is_error = isinstance(content_type, str) and content_type.endswith(
            "_error"
        )
        try:
            if hasattr(content, "model_dump"):
                dumped_content = content.model_dump(mode="json")
            elif isinstance(content, list):
                # Round-trip Pydantic items via model_dump — otherwise
                # ``json.dumps(default=str)`` would store repr strings.
                dumped_content = [
                    item.model_dump(mode="json")
                    if hasattr(item, "model_dump")
                    else item
                    for item in content
                ]
            else:
                dumped_content = content
        except Exception:
            logger.exception(
                "loop_server_tool_content_dump_failed",
                tool_name=use_info["tool_name"],
                tool_use_id=tool_use_id,
            )
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("turn_id", str(turn_id))
                scope.set_tag("conversation_id", str(conversation_id))
                scope.set_tag("tool_use_id", tool_use_id)
                scope.set_tag("tool_name", use_info["tool_name"])
                sentry_sdk.capture_message(
                    "loop_server_tool_content_dump_failed",
                    level="warning",
                )
            dumped_content = {"_dump_failed": True}

        if is_error:
            status = "error"
            error_code = (
                getattr(content, "error_code", None)
                if content is not None
                else None
            )
            error_message = (
                str(error_code) if error_code is not None else "unknown_error"
            )
            output_payload: dict[str, Any] | None = None
        else:
            status = "success"
            error_message = None
            output_payload = {"content": _truncate_for_audit(dumped_content)}

        async with db_factory() as db:
            await ConversationRepository.record_tool_execution(
                db,
                model_invocation_id=invocation_id,
                tool_name=use_info["tool_name"],
                tool_use_id=tool_use_id,
                input_payload=use_info["input_payload"],
                status=status,
                output_payload=output_payload,
                error_message=error_message,
            )


async def _flush_orphan_server_tool_uses(
    *,
    pending_uses: dict[str, dict[str, Any]],
    open_status_blocks: dict[str, str],
    status_block_records: dict[str, dict[str, Any]],
    invocation_id: uuid.UUID | None,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    turn_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    """Close any server-tool uses that never got a matching result.

    Anything still in ``pending_uses`` is a contract violation or an
    early-ending turn. Emits a failed-state ``BlockData`` + ``BlockEnd``
    for each orphan pill and writes a ``status=error`` audit row.
    """
    for tool_use_id, use_info in list(pending_uses.items()):
        logger.warning(
            "loop_server_tool_missing_result_block",
            tool_name=use_info["tool_name"],
            tool_use_id=tool_use_id,
        )
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("turn_id", str(turn_id))
            scope.set_tag("conversation_id", str(conversation_id))
            scope.set_tag("tool_use_id", tool_use_id)
            scope.set_tag("tool_name", use_info["tool_name"])
            sentry_sdk.capture_message(
                "loop_server_tool_missing_result_block",
                level="warning",
            )

        status_block_id = open_status_blocks.pop(tool_use_id, None)
        if status_block_id is not None:
            await sse_emitter.emit(
                BlockData(
                    block_id=status_block_id, data={"state": "failed"}
                )
            )
            await sse_emitter.emit(BlockEnd(block_id=status_block_id))
            if tool_use_id in status_block_records:
                status_block_records[tool_use_id]["state"] = "failed"

        if invocation_id is not None:
            async with db_factory() as db:
                await ConversationRepository.record_tool_execution(
                    db,
                    model_invocation_id=invocation_id,
                    tool_name=use_info["tool_name"],
                    tool_use_id=tool_use_id,
                    input_payload=use_info["input_payload"],
                    status="error",
                    output_payload=None,
                    error_message="missing_result_block",
                )

    pending_uses.clear()


def _to_anthropic_content(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip Sevino-only fields before sending history back to Anthropic.

    Drops the ``block_id`` we add for iOS correlation and UI-only variants
    (``status``, ``stock_card``, ``thinking``) — Anthropic 400s on unknown
    types. Tool-use context is lost across turns; the assistant text is
    sufficient continuity.
    """
    converted: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "text":
            converted.append(
                {"type": "text", "text": block.get("text", "")}
            )
        elif block.get("type") == "context":
            data = block.get("data", {})
            converted.append(
                {
                    "type": "text",
                    "text": (
                        "[Attached context from the user's open modal — "
                        "use this data to inform your response]\n"
                        + json.dumps(data, separators=(",", ":"), default=str)
                    ),
                }
            )
    return converted


def _estimate_thinking_tokens(response_content: list[dict[str, Any]]) -> int:
    # Heuristic — Anthropic doesn't expose a per-block token count.
    total = 0
    for block in response_content:
        if block.get("type") == "thinking":
            text = block.get("thinking") or ""
            if isinstance(text, str):
                total += len(text) // _CHARS_PER_TOKEN
    return total


async def _finalize_agent_turn_row(
    db_factory: DbSessionFactory,
    *,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    terminal_state: str,
    error_code: ErrorCode | None,
    cancellation_reason: str | None,
    iterations_count: int,
    totals: dict[str, int],
    assistant_blocks: list[dict[str, Any]],
) -> None:
    """Persist the terminal state — assistant message + ``complete_agent_turn``.

    Run via ``asyncio.shield`` from the outer finally: under sse-starlette
    teardown, raw awaits in the finally were re-cancelled before COMMIT.
    Errors are logged rather than re-raised — by here the row is the only
    signal left.
    """
    try:
        assistant_message_id: uuid.UUID | None = None
        if assistant_blocks:
            async with db_factory() as db:
                msg = await ConversationRepository.append_assistant_message(
                    db,
                    conversation_id=conversation_id,
                    content_blocks=assistant_blocks,
                )
                assistant_message_id = msg.id

        async with db_factory() as db:
            await ConversationRepository.complete_agent_turn(
                db,
                agent_turn_id=turn_id,
                terminal_state=terminal_state,
                assistant_message_id=assistant_message_id,
                cancellation_reason=cancellation_reason,
                error_code=(
                    error_code.value if error_code is not None else None
                ),
                iterations_count=iterations_count,
                total_input_tokens=totals["input"],
                total_output_tokens=totals["output"],
                total_cache_read_tokens=totals["cache_read"],
                total_cache_creation_tokens=totals["cache_creation"],
                total_thinking_tokens=totals["thinking"],
                total_cost_usd_micros=totals["cost"],
            )
    except Exception:
        logger.exception(
            "agent_turn_finalize_failed",
            turn_id=str(turn_id),
            terminal_state=terminal_state,
        )


class _RecordingEmitter:
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


class _ToolDispatchOutcome:
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
        async with db_factory() as db:
            await ConversationRepository.record_tool_execution(
                db,
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
        async with db_factory() as db:
            await ConversationRepository.record_tool_execution(
                db,
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
    recording_emitter = _RecordingEmitter(sse_emitter)
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
        async with db_factory() as db:
            await ConversationRepository.record_tool_execution(
                db,
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

    async with db_factory() as db:
        await ConversationRepository.record_tool_execution(
            db,
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


async def _dispatch_tool_uses(
    *,
    response_blocks: list[Any],
    tool_registry: ToolRegistry,
    user_id: uuid.UUID,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
    invocation_id: uuid.UUID,
) -> _ToolDispatchOutcome:
    """Run every ``tool_use`` block in parallel.

    Results aggregate in input order. Wire events for siblings interleave
    on the wire; iOS correlates by block_id. The first error becomes the
    iteration's ``terminal_error_code``; siblings still run.
    """
    outcome = _ToolDispatchOutcome()

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


async def run_agent_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
    user_context: dict[str, Any] | None = None,
    anthropic_client: AsyncAnthropic,
    db_factory: DbSessionFactory,
    tool_registry: ToolRegistry,
    system_prompt: SystemPrompt,
    model_config: ModelConfig,
    hard_caps: HardCaps,
    langfuse: LangfuseClient,
    environment: str,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
    disconnect_check: Callable[[], Awaitable[bool]] | None = None,
    server_tools_config: ServerToolsConfig = DISABLED_SERVER_TOOLS,
) -> AgentTurnResult:
    """Run one agent turn end-to-end.

    Anthropic errors and cap breaches don't raise — they're persisted with
    ``terminal_state='error'``. ``CancelledError`` propagates after
    partial state is flushed.

    Raises ``ValueError`` if ``max_output_tokens <= thinking budget``;
    Anthropic 400s on every call otherwise.

    The body runs inside one outer try/except/finally so cancellation at
    any await still finalises the agent_turn row.

    ``disconnect_check`` is not wired in production —
    ``BaseHTTPMiddleware`` consumes the ASGI receive channel upstream, so
    ``request.is_disconnected`` never fires. Cancellation arrives via
    ``task.cancel()`` when the SSE asyncgen closes.
    """
    if hard_caps.max_output_tokens <= _THINKING_BUDGET_TOKENS:
        raise ValueError(
            f"hard_caps.max_output_tokens ({hard_caps.max_output_tokens}) "
            f"must be > thinking budget ({_THINKING_BUDGET_TOKENS}); "
            f"Anthropic requires budget_tokens < max_tokens."
        )

    # Initialised before the first await so the finally has well-defined
    # values even on early cancellation. The finally guards on ``turn_id``.
    turn_id: uuid.UUID | None = None
    state = LoopState(started_at_monotonic=time.monotonic())
    assistant_blocks: list[dict[str, Any]] = []
    totals = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "thinking": 0,
        "cost": 0,
    }
    terminal_state: str | None = None
    error_code: ErrorCode | None = None
    cancellation_reason: str | None = None
    # Gates the terminal SSE frame — only true after a normal break.
    completed_normally = False

    try:
        # Persist the user message first so a crash mid-turn doesn't lose
        # the user's input. ``block_id`` is required for the iOS resume
        # decoder.
        async with db_factory() as db:
            content_blocks: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "block_id": str(ULID()),
                    "text": user_message,
                }
            ]
            if user_context:
                content_blocks.append(
                    {
                        "type": "context",
                        "block_id": str(ULID()),
                        "data": user_context,
                    }
                )
            user_msg = await ConversationRepository.append_user_message(
                db,
                conversation_id=conversation_id,
                content_blocks=content_blocks,
            )
            user_message_id = user_msg.id

        async with db_factory() as db:
            history = await ConversationRepository.load_history(db, conversation_id)
        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": _to_anthropic_content(m.content_blocks)}
            for m in history
        ]

        # Once this row is open, the outer finally guarantees we close it.
        async with db_factory() as db:
            turn = await ConversationRepository.start_agent_turn(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                user_message_id=user_message_id,
                prompt_hash=system_prompt.hash,
                model_id=model_config.model_id,
            )
            turn_id = turn.id

        await sse_emitter.emit(
            TurnStarted(turn_id=turn_id, conversation_id=conversation_id)
        )

        # Mark the system block as a cache breakpoint so Anthropic reuses
        # everything up to the marker across turns within the 5m TTL —
        # input cost drops to the cache-read rate on hits.
        request_system: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system_prompt.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # ``turn_id.hex`` is the 32-char lowercase form W3C trace context
        # requires, so a Langfuse trace looks up directly by
        # ``agent_turns.id`` — no separate trace_id column needed.
        trace_context = {"trace_id": turn_id.hex}

        with langfuse.start_as_current_observation(
            as_type="agent",
            name="agent_turn",
            trace_context=trace_context,
            input={"user_message": user_message},
        ) as turn_span:
            # ``propagate_attributes`` must be entered AFTER the outer span
            # so the span is the active OTel span when attributes are set;
            # otherwise the tags don't reach the trace.
            with propagate_attributes(
                user_id=str(user_id),
                session_id=str(conversation_id),
                tags=[
                    f"environment:{environment}",
                    f"model:{model_config.model_id}",
                    f"prompt_hash:{system_prompt.hash}",
                ],
                metadata={
                    "turn_id": str(turn_id),
                    "prompt_hash": system_prompt.hash,
                    "environment": environment,
                    "model_id": model_config.model_id,
                },
            ):
                # Turn-scoped — Anthropic can defer a result to a later iteration.
                open_status_blocks: dict[str, str] = {}
                status_block_records: dict[str, dict[str, Any]] = {}
                pending_server_tool_uses: dict[str, dict[str, Any]] = {}
                status_blocks_persisted: set[str] = set()
                invocation_id: uuid.UUID | None = None
                try:
                    while True:
                        # Self-raise so the except below sets
                        # ``terminal_state='cancelled'`` deterministically.
                        if disconnect_check is not None and await disconnect_check():
                            raise asyncio.CancelledError

                        breach = check_caps(state, hard_caps)
                        if breach is not None:
                            terminal_state = breach.value
                            error_code = _BREACH_TO_ERROR_CODE[breach]
                            break

                        iteration_index = state.iterations

                        create_kwargs: dict[str, Any] = {
                            "model": model_config.model_id,
                            "system": request_system,
                            "messages": messages,
                            "max_tokens": hard_caps.max_output_tokens,
                            "thinking": {
                                "type": "enabled",
                                "budget_tokens": _THINKING_BUDGET_TOKENS,
                            },
                        }
                        # Anthropic 400s on empty tools. cache_control caches
                        # the tools array with the system prompt.
                        server_tool_specs = _build_server_tool_specs(
                            server_tools_config
                        )
                        registry_specs: list[dict[str, Any]] = (
                            list(tool_registry.to_anthropic_spec())
                            if not tool_registry.is_empty
                            else []
                        )
                        combined_tools = [*server_tool_specs, *registry_specs]
                        if combined_tools:
                            combined_tools[-1] = {
                                **combined_tools[-1],
                                "cache_control": {"type": "ephemeral"},
                            }
                            create_kwargs["tools"] = combined_tools

                        # Copy ``messages`` — the loop mutates it after the
                        # call, and Langfuse would otherwise see the new state.
                        with langfuse.start_as_current_observation(
                            as_type="generation",
                            name="anthropic.messages.create",
                            model=model_config.model_id,
                            input={
                                "system": request_system,
                                "messages": list(messages),
                            },
                            metadata={"iteration_index": iteration_index},
                        ) as gen:
                            iter_started = time.monotonic()
                            # Wire shapes:
                            #   text:               block_start → text_delta* → block_end
                            #   thinking:           block_start(streaming) → text_delta* → block_data(complete) → block_end
                            #   redacted_thinking:  block_start(redacted, complete) → block_end
                            open_text_blocks: dict[int, str] = {}
                            open_thinking_blocks: dict[int, str] = {}
                            text_deltas_seen = 0
                            # On mid-stream cancel ``get_final_message`` never
                            # returns, so this is the only record of what
                            # reached the wire.
                            accumulated_text: dict[int, str] = {}
                            try:
                                async with anthropic_client.messages.stream(
                                    **create_kwargs
                                ) as stream:
                                    try:
                                        async for chunk in stream:
                                            if chunk.type == "content_block_start":
                                                cb_type = chunk.content_block.type
                                                if cb_type == "text":
                                                    block_id = str(ULID())
                                                    open_text_blocks[chunk.index] = (
                                                        block_id
                                                    )
                                                    accumulated_text[chunk.index] = ""
                                                    await sse_emitter.emit(
                                                        BlockStart(
                                                            block={
                                                                "type": "text",
                                                                "block_id": block_id,
                                                                "text": "",
                                                            }
                                                        )
                                                    )
                                                elif (
                                                    server_tools_config.any_enabled
                                                    and cb_type == "server_tool_use"
                                                ):
                                                    tool_use_id = getattr(
                                                        chunk.content_block,
                                                        "id",
                                                        None,
                                                    )
                                                    raw_name = getattr(
                                                        chunk.content_block,
                                                        "name",
                                                        None,
                                                    )
                                                    if (
                                                        isinstance(tool_use_id, str)
                                                        and tool_use_id
                                                    ):
                                                        status_block_id = str(ULID())
                                                        open_status_blocks[
                                                            tool_use_id
                                                        ] = status_block_id
                                                        record: dict[str, Any] = {
                                                            "type": "status",
                                                            "block_id": (
                                                                status_block_id
                                                            ),
                                                            "label": (
                                                                _server_tool_status_label(
                                                                    raw_name
                                                                )
                                                            ),
                                                            "state": "active",
                                                        }
                                                        status_block_records[
                                                            tool_use_id
                                                        ] = record
                                                        await sse_emitter.emit(
                                                            BlockStart(block=record)
                                                        )
                                                elif (
                                                    server_tools_config.any_enabled
                                                    and cb_type
                                                    in _SERVER_TOOL_RESULT_BLOCK_TYPES
                                                ):
                                                    result_block = chunk.content_block
                                                    tool_use_id = getattr(
                                                        result_block,
                                                        "tool_use_id",
                                                        None,
                                                    )
                                                    if (
                                                        isinstance(tool_use_id, str)
                                                        and tool_use_id
                                                    ):
                                                        status_block_id = (
                                                            open_status_blocks.pop(
                                                                tool_use_id, None
                                                            )
                                                        )
                                                        if status_block_id is not None:
                                                            new_state = (
                                                                _result_block_status_state(
                                                                    result_block
                                                                )
                                                            )
                                                            await sse_emitter.emit(
                                                                BlockData(
                                                                    block_id=(
                                                                        status_block_id
                                                                    ),
                                                                    data={
                                                                        "state": (
                                                                            new_state
                                                                        )
                                                                    },
                                                                )
                                                            )
                                                            await sse_emitter.emit(
                                                                BlockEnd(
                                                                    block_id=(
                                                                        status_block_id
                                                                    )
                                                                )
                                                            )
                                                            status_block_records[
                                                                tool_use_id
                                                            ]["state"] = new_state
                                                elif cb_type == "thinking":
                                                    block_id = str(ULID())
                                                    open_thinking_blocks[
                                                        chunk.index
                                                    ] = block_id
                                                    await sse_emitter.emit(
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
                                                    # Skip ``open_thinking_blocks`` so the
                                                    # delta/stop branches stay no-ops —
                                                    # encrypted payload, no deltas.
                                                    block_id = str(ULID())
                                                    await sse_emitter.emit(
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
                                                    await sse_emitter.emit(
                                                        BlockEnd(block_id=block_id)
                                                    )
                                            elif chunk.type == "content_block_delta":
                                                if (
                                                    chunk.delta.type == "text_delta"
                                                    and chunk.index in open_text_blocks
                                                ):
                                                    accumulated_text[chunk.index] += (
                                                        chunk.delta.text
                                                    )
                                                    await sse_emitter.emit(
                                                        TextDelta(
                                                            block_id=open_text_blocks[
                                                                chunk.index
                                                            ],
                                                            text=chunk.delta.text,
                                                        )
                                                    )
                                                    text_deltas_seen += 1
                                                    # Poll on cadence so iOS
                                                    # close lands within a few
                                                    # hundred ms.
                                                    if (
                                                        disconnect_check is not None
                                                        and text_deltas_seen
                                                        % _DISCONNECT_CHECK_DELTA_INTERVAL
                                                        == 0
                                                        and await disconnect_check()
                                                    ):
                                                        raise asyncio.CancelledError
                                                elif (
                                                    chunk.delta.type
                                                    == "thinking_delta"
                                                    and chunk.index
                                                    in open_thinking_blocks
                                                ):
                                                    await sse_emitter.emit(
                                                        TextDelta(
                                                            block_id=open_thinking_blocks[
                                                                chunk.index
                                                            ],
                                                            text=chunk.delta.thinking,
                                                        )
                                                    )
                                                    text_deltas_seen += 1
                                                    if (
                                                        disconnect_check is not None
                                                        and text_deltas_seen
                                                        % _DISCONNECT_CHECK_DELTA_INTERVAL
                                                        == 0
                                                        and await disconnect_check()
                                                    ):
                                                        raise asyncio.CancelledError
                                            elif chunk.type == "content_block_stop":
                                                block_id = open_text_blocks.get(
                                                    chunk.index
                                                )
                                                if block_id is not None:
                                                    await sse_emitter.emit(
                                                        BlockEnd(block_id=block_id)
                                                    )
                                                else:
                                                    thinking_block_id = (
                                                        open_thinking_blocks.get(
                                                            chunk.index
                                                        )
                                                    )
                                                    if thinking_block_id is not None:
                                                        await sse_emitter.emit(
                                                            BlockData(
                                                                block_id=(
                                                                    thinking_block_id
                                                                ),
                                                                data={
                                                                    "state": (
                                                                        "complete"
                                                                    )
                                                                },
                                                            )
                                                        )
                                                        await sse_emitter.emit(
                                                            BlockEnd(
                                                                block_id=(
                                                                    thinking_block_id
                                                                )
                                                            )
                                                        )
                                        response = await stream.get_final_message()
                                    except asyncio.CancelledError:
                                        # Close upstream eagerly so the
                                        # connection is released before the
                                        # outer finally hits the DB.
                                        await stream.close()
                                        for index, block_id in open_text_blocks.items():
                                            partial = accumulated_text.get(index, "")
                                            if partial:
                                                assistant_blocks.append(
                                                    {
                                                        "type": "text",
                                                        "block_id": block_id,
                                                        "text": partial,
                                                    }
                                                )
                                        # On cancel text/pill interleaving is
                                        # lost — pills land after partial text.
                                        _append_status_blocks_for_persistence(
                                            tool_use_ids=list(
                                                status_block_records.keys()
                                            ),
                                            status_block_records=status_block_records,
                                            status_blocks_persisted=status_blocks_persisted,
                                            assistant_blocks=assistant_blocks,
                                        )
                                        gen.update(
                                            level="WARNING",
                                            status_message="cancelled",
                                        )
                                        raise
                            except Exception as exc:
                                error_code = to_error_code(exc)
                                terminal_state = "error"
                                # We catch the exception, so tag the gen
                                # explicitly or Langfuse will mark it OK.
                                gen.update(
                                    level="ERROR",
                                    status_message=f"{type(exc).__name__}: {exc}",
                                )
                                break
                            latency_ms = int((time.monotonic() - iter_started) * 1000)

                            # ``scrub_blocks`` strips SDK-only fields the API
                            # accepts on output but rejects as input.
                            response_content = scrub_blocks(
                                [
                                    block.model_dump(mode="json")
                                    for block in response.content
                                ]
                            )
                            cost = cost_usd_micros(
                                response.usage, model_config.model_id
                            )
                            iter_thinking_tokens = _estimate_thinking_tokens(
                                response_content
                            )
                            cache_read = (
                                response.usage.cache_read_input_tokens or 0
                            )
                            cache_create = (
                                response.usage.cache_creation_input_tokens or 0
                            )
                            # Explicit ``total`` so Langfuse doesn't auto-sum
                            # and double-count thinking (it's already in
                            # ``output_tokens``).
                            gen.update(
                                output=response_content,
                                usage_details={
                                    "input": response.usage.input_tokens,
                                    "output": response.usage.output_tokens,
                                    "cache_read_input_tokens": cache_read,
                                    "cache_creation_input_tokens": cache_create,
                                    "thinking": iter_thinking_tokens,
                                    "total": (
                                        response.usage.input_tokens
                                        + response.usage.output_tokens
                                        + cache_read
                                        + cache_create
                                    ),
                                },
                                cost_details={"total": cost / 1_000_000},
                            )

                        async with db_factory() as db:
                            invocation = (
                                await ConversationRepository.record_model_invocation(
                                    db,
                                    agent_turn_id=turn_id,
                                    iteration_index=iteration_index,
                                    model_id=model_config.model_id,
                                    request_system=request_system,
                                    request_messages=messages,
                                    response_content=response_content,
                                    stop_reason=response.stop_reason,
                                    input_tokens=response.usage.input_tokens,
                                    output_tokens=response.usage.output_tokens,
                                    cache_read_input_tokens=cache_read,
                                    cache_creation_input_tokens=cache_create,
                                    thinking_tokens=iter_thinking_tokens,
                                    cost_usd_micros=cost,
                                    latency_ms=latency_ms,
                                )
                            )
                            invocation_id = invocation.id

                        if server_tools_config.any_enabled:
                            await _record_server_tool_executions(
                                response_blocks=response.content,
                                pending_uses=pending_server_tool_uses,
                                invocation_id=invocation_id,
                                db_factory=db_factory,
                                turn_id=turn_id,
                                conversation_id=conversation_id,
                            )

                        state.iterations += 1
                        state.output_tokens += response.usage.output_tokens
                        totals["input"] += response.usage.input_tokens
                        totals["output"] += response.usage.output_tokens
                        totals["cache_read"] += cache_read
                        totals["cache_creation"] += cache_create
                        totals["thinking"] += iter_thinking_tokens
                        totals["cost"] += cost

                        messages.append(
                            {"role": "assistant", "content": response_content}
                        )

                        # Preserve order so reload matches the live stream.
                        for index, block in enumerate(response.content):
                            if block.type == "text":
                                block_id = open_text_blocks.get(index)
                                if block_id is None:
                                    # Persisted block_id won't match any
                                    # streamed block_start — iOS correlation
                                    # breaks; log loudly.
                                    block_id = str(ULID())
                                    logger.warning(
                                        "loop_text_block_id_fallback",
                                        turn_id=str(turn_id),
                                        iteration_index=iteration_index,
                                        response_index=index,
                                        streamed_indices=sorted(
                                            open_text_blocks.keys()
                                        ),
                                    )
                                assistant_blocks.append(
                                    {
                                        "type": "text",
                                        "block_id": block_id,
                                        "text": block.text,
                                    }
                                )
                            elif block.type == "server_tool_use":
                                tool_use_id = getattr(block, "id", None)
                                if isinstance(tool_use_id, str):
                                    _append_status_blocks_for_persistence(
                                        tool_use_ids=[tool_use_id],
                                        status_block_records=status_block_records,
                                        status_blocks_persisted=status_blocks_persisted,
                                        assistant_blocks=assistant_blocks,
                                    )

                        if response.stop_reason == "end_turn":
                            terminal_state = "end_turn"
                            break
                        if response.stop_reason == "max_tokens":
                            terminal_state = "output_token_limit"
                            error_code = ErrorCode.OUTPUT_TOKEN_LIMIT
                            break
                        if response.stop_reason == "tool_use":
                            tool_outcomes = await _dispatch_tool_uses(
                                response_blocks=response.content,
                                tool_registry=tool_registry,
                                user_id=user_id,
                                db_factory=db_factory,
                                sse_emitter=sse_emitter,
                                http_clients=http_clients,
                                invocation_id=invocation_id,
                            )
                            if tool_outcomes.terminal_error_code is not None:
                                terminal_state = "error"
                                error_code = tool_outcomes.terminal_error_code
                                assistant_blocks.extend(
                                    tool_outcomes.ui_block_dicts
                                )
                                break
                            # ``tool_use`` stop with no tool_use blocks would
                            # loop forever — fail it.
                            if tool_outcomes.tool_call_count == 0:
                                terminal_state = "error"
                                error_code = ErrorCode.INTERNAL_ERROR
                                break
                            assistant_blocks.extend(
                                tool_outcomes.ui_block_dicts
                            )
                            state.tool_calls += tool_outcomes.tool_call_count
                            # Anthropic expects tool_results on a follow-up
                            # ``user`` message.
                            messages.append(
                                {
                                    "role": "user",
                                    "content": tool_outcomes.tool_result_blocks,
                                }
                            )
                            continue
                        if response.stop_reason == "pause_turn":
                            # Continue verbatim — already appended to messages
                            # so signatures roundtrip intact.
                            continue
                        # Refusal, stop_sequence, etc. — record verbatim.
                        terminal_state = response.stop_reason or "unknown"
                        break
                    # Close orphan server-tool uses so mid-turn errors don't
                    # leave pills stuck active.
                    if server_tools_config.any_enabled:
                        await _flush_orphan_server_tool_uses(
                            pending_uses=pending_server_tool_uses,
                            open_status_blocks=open_status_blocks,
                            status_block_records=status_block_records,
                            invocation_id=invocation_id,
                            db_factory=db_factory,
                            sse_emitter=sse_emitter,
                            turn_id=turn_id,
                            conversation_id=conversation_id,
                        )
                    completed_normally = True
                except asyncio.CancelledError:
                    terminal_state = "cancelled"
                    error_code = ErrorCode.CANCELLED
                    cancellation_reason = _DEFAULT_CANCELLATION_REASON
                    # Flip active pills in-place so reload shows them failed,
                    # not phantom spinners. The records dict shares refs with
                    # ``assistant_blocks``.
                    for record in status_block_records.values():
                        if record.get("state") == "active":
                            record["state"] = "failed"
                    raise
                finally:
                    # Must run while the langfuse span is still the active
                    # OTel span. Guards handle BaseException paths.
                    inner_terminal_state = terminal_state or "error"
                    inner_error_code = (
                        error_code
                        if error_code is not None
                        else (
                            ErrorCode.INTERNAL_ERROR
                            if terminal_state is None
                            else None
                        )
                    )
                    turn_span.update(
                        output={
                            "terminal_state": inner_terminal_state,
                            "iterations": state.iterations,
                            "assistant_blocks": assistant_blocks,
                        },
                        level=(
                            "ERROR" if inner_error_code is not None else "DEFAULT"
                        ),
                        status_message=(
                            inner_error_code.value
                            if inner_error_code is not None
                            else None
                        ),
                    )
    except asyncio.CancelledError:
        # Cancellation before the inner try (during user-message persist,
        # history load, start_agent_turn, ...). Without this clause the
        # row sits non-terminal forever.
        if terminal_state is None:
            terminal_state = "cancelled"
            error_code = ErrorCode.CANCELLED
        if cancellation_reason is None:
            cancellation_reason = _DEFAULT_CANCELLATION_REASON
        raise
    finally:
        # Unhandled non-cancel exception escaped — mark as error so the
        # row never sits non-terminal.
        if terminal_state is None:
            terminal_state = "error"
            error_code = ErrorCode.INTERNAL_ERROR

        # ``shield`` so writes survive parent cancellation under
        # sse-starlette teardown.
        if turn_id is not None:
            await asyncio.shield(
                _finalize_agent_turn_row(
                    db_factory,
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    terminal_state=terminal_state,
                    error_code=error_code,
                    cancellation_reason=cancellation_reason,
                    iterations_count=state.iterations,
                    totals=totals,
                    assistant_blocks=assistant_blocks,
                )
            )

        # Only emit on normal break; unhandled exceptions are surfaced by
        # the caller to avoid two terminal frames.
        if completed_normally and turn_id is not None:
            if error_code is not None:
                await sse_emitter.emit(
                    Error(
                        code=error_code,
                        message=f"terminal_state={terminal_state}",
                    )
                )
            else:
                await sse_emitter.emit(
                    TurnCompleted(
                        turn_id=turn_id,
                        terminal_state=terminal_state,
                        total_cost_usd_micros=totals["cost"],
                        iterations_count=state.iterations,
                    )
                )

    # Only reachable after a normal break.
    assert turn_id is not None
    return AgentTurnResult(
        turn_id=turn_id,
        terminal_state=terminal_state,
        assistant_message_blocks=assistant_blocks,
        total_cost_usd_micros=totals["cost"],
        iterations_count=state.iterations,
    )
