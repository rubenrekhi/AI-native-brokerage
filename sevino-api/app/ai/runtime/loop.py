"""Agent loop core.

Per AI v0 plan A1.6 (sevino-api/docs/ai-v0-plan.md): a pure async function
that runs one agent turn end-to-end. v0 has no tools, so the loop runs
exactly one Anthropic call per turn (``stop_reason == "end_turn"``
immediately) — but the loop is structured to handle multi-iteration tool
use without restructuring once Project C lands.

A1.7 adds extended thinking: every Anthropic call sends
``thinking={"type": "enabled", "budget_tokens": 1024}`` and the loop
continues iterating on ``stop_reason == "pause_turn"`` (Anthropic's
documented "continue verbatim" signal). The prior assistant content —
including ``thinking`` blocks **with their signatures** — is appended to
``messages`` before the next call so iteration N+1's request roundtrips
the iteration-N signature byte-for-byte. ``model_invocations.response_content``
is the source of truth (decision R1 in the plan).

B2.4 wires the loop to the SSE transport. The caller passes an
:class:`SSEEmitter`; the loop emits ``turn_started`` once
``agent_turns.id`` is known, then ``block_start`` / ``text_delta`` /
``block_end`` per text block as Anthropic streams, and finally
``turn_completed`` (or ``error`` on cap breach / Anthropic failure) when
the turn finalises. Block IDs are server-assigned ULIDs that round-trip
through ``messages.content_blocks`` so iOS can correlate streamed
deltas with the final persisted message.

**No FastAPI imports.** All collaborators (Anthropic client, DB factory,
tool registry, system prompt, model config, hard caps, SSE emitter) are
passed in by the caller (typically the chat-turn endpoint added in A1.9
and converted to SSE in B2.3) so the same function is reusable by
sub-agents and trivially testable in isolation.

Persistence pattern (decision D12): the loop opens a fresh ``AsyncSession``
via ``db_factory`` for every write — user message, agent_turn start,
each model_invocation, assistant message, agent_turn complete. Audit rows
are durable mid-turn rather than batched at the end.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pydantic
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
    AgentTurnResult,
    LoopState,
    ModelConfig,
    ToolRegistry,
)
from app.ai.tools.base import ToolContext, ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
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

# CapBreach values map onto ErrorCode values surfaced in the SSE error event.
# TIMEOUT has no clean counterpart — ErrorCode lacks a TURN_TIMEOUT variant —
# so it folds into INTERNAL_ERROR for now. Adding TURN_TIMEOUT is a one-line
# follow-up.
_BREACH_TO_ERROR_CODE: dict[CapBreach, ErrorCode] = {
    CapBreach.ITERATION_LIMIT: ErrorCode.TURN_ITERATION_LIMIT,
    CapBreach.TOOL_CALL_LIMIT: ErrorCode.TOOL_CALL_LIMIT,
    CapBreach.OUTPUT_TOKEN_LIMIT: ErrorCode.OUTPUT_TOKEN_LIMIT,
    CapBreach.TIMEOUT: ErrorCode.INTERNAL_ERROR,
}

# A1.7. Anthropic requires budget_tokens >= 1024 and < max_tokens for
# extended thinking. v0 hardcodes the floor; future model configs can
# carry a per-turn override (see ``ModelConfig`` docstring).
_THINKING_BUDGET_TOKENS = 1024

# Rough chars-per-token used to estimate thinking token usage from the
# visible thinking block content. Anthropic bundles thinking tokens into
# ``Usage.output_tokens`` and does not expose a per-block breakdown, so
# this heuristic gives an order-of-magnitude indicator for the
# ``thinking_tokens`` audit columns. ``redacted_thinking`` blocks have
# encrypted content that doesn't correlate with token count, so they
# contribute zero — the audit row will undercount when redacted thinking
# fires, which is acceptable for v0 observability.
_CHARS_PER_TOKEN = 4

# B3.3: how often to poll ``disconnect_check`` mid-stream. Polled after
# every Nth ``text_delta`` so an iOS disconnect lands a CancelledError
# inside the loop within a few hundred milliseconds (Anthropic typically
# streams ~50 deltas/s on Sonnet). Lower = faster cancel but more
# is_disconnected() ASGI-receive polls; higher = cheaper but laggier.
_DISCONNECT_CHECK_DELTA_INTERVAL = 16

# B3.4: default ``cancellation_reason`` persisted on the ``agent_turns``
# row when the loop is cancelled. v0 has only one cancellation source
# (the framework cancels the driver task on client disconnect), so a
# constant is fine; later phases can plumb through an explicit reason
# (e.g. ``"server_shutdown"``, ``"timeout"``).
_DEFAULT_CANCELLATION_REASON = "client_disconnect"


def _to_anthropic_content(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip Sevino-only fields from persisted blocks before re-sending.

    ``messages.content_blocks`` JSONB carries a server-assigned ``block_id``
    on text blocks (B2.4) so iOS can correlate the persisted row with the
    SSE wire envelope. Anthropic's content-block schema doesn't accept
    that field, and a follow-up turn that loads history verbatim would
    400 on the unknown property — silently caught by the loop's inner
    ``except Exception`` and reported as ``INTERNAL_ERROR``.

    This is the boundary that translates *persisted* blocks back to the
    *request* shape Anthropic expects. Within a single turn we never go
    through here — the assistant content appended on each iteration is
    the verbatim ``response_content`` from ``model_invocations``, which
    is already in the Anthropic shape (and carries the thinking
    signatures A1.7's R1 contract requires).

    UI-only block variants (``status``, ``stock_card``, …) introduced in
    Project C are dropped entirely — they never went to the model in
    the first place, and Anthropic 400s on unknown ``type`` values.
    Subsequent turns therefore lose tool-use context across turns; in
    v0 the assistant text answer is sufficient continuity.
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
        # Other block types are UI-only artefacts (StatusBlock,
        # StockCardBlock, …) — silently skip rather than forwarding to
        # Anthropic.
    return converted


def _estimate_thinking_tokens(response_content: list[dict[str, Any]]) -> int:
    """Approximate thinking tokens from the visible ``thinking`` block text.

    See ``_CHARS_PER_TOKEN`` for why this is a heuristic rather than an
    exact count.
    """
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
    """Persist the terminal state of an agent turn — assistant message
    plus ``complete_agent_turn`` write. Designed to be run via
    :func:`asyncio.shield` from ``run_agent_turn``'s outer ``finally``
    so the DB writes survive even when the parent task is being
    cancelled.

    On Railway under sse-starlette's task-group cancellation cascade we
    observed agent_turn rows getting stuck in non-terminal state — the
    parent task's ``await`` inside the ``finally`` was being interrupted
    by additional cancellation signals before the COMMIT landed. Routing
    the writes through ``asyncio.shield(...)`` puts them in a child task
    whose own cancel scope is independent of the parent: when the parent
    is cancelled, ``shield`` raises ``CancelledError`` to the parent but
    the child task continues to run on the event loop until the writes
    finish. Errors are caught and logged here rather than surfaced to
    the caller, since by the time we're finalising there's nothing the
    caller could do — the row is the audit-trail and we'd rather have a
    log than nothing.
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
    """SSE emitter wrapper that records ``BlockStart`` ``block_id`` values.

    Forwards every event to ``underlying`` unchanged. The set of seen
    ``block_id`` values lets the loop's tool-result branch decide whether
    a tool already announced a UI block (incremental streaming case —
    C1.4) or whether the loop must emit ``block_start`` itself before
    ``block_end`` (simple case where the tool only returned the final
    block in :class:`ToolResult`).

    The underlying type is the :class:`SSEEmitter` Protocol owned by
    ``app.ai.tools.base`` — both :class:`app.ai.transport.emitter.SSEEmitter`
    (the real producer queue) and test fakes implement it.
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
    """Aggregated state of a single iteration's tool-use processing.

    On a fully successful iteration ``terminal_error_code`` is ``None``
    and the loop appends ``tool_result_blocks`` to its messages list and
    continues. On any tool failure (lookup, validation, or
    ``execute``-time exception) ``terminal_error_code`` is set to the
    error from the *first* failing block (in tool_use input order) and
    the loop sets ``terminal_state='error'`` and breaks out. SEV-565:
    every ``tool_use`` block in the response still gets its
    ``tool_executions`` row written before the loop aborts — the parallel
    dispatcher does not short-circuit sibling tools on a single failure.
    Order is preserved (matches Anthropic's assistant content order).
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
    """Outcome of dispatching one ``tool_use`` block.

    Populated by :func:`_dispatch_one_tool_use` and aggregated in input
    order by :func:`_dispatch_tool_uses`. The per-block coroutine catches
    its own lookup / validation / execute exceptions and surfaces them
    via ``error_code``; only programming bugs (e.g. a DB write failure
    inside :meth:`ConversationRepository.record_tool_execution`) raise
    out, which is the contract :func:`asyncio.gather` expects so the
    outer loop's ``except Exception`` can map them to ``INTERNAL_ERROR``.
    """

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
    """Process a single ``tool_use`` block end-to-end.

    Registry lookup → input validation → ``execute`` → ``tool_executions``
    persistence → wire-event emission for the returned ``ui_block``.
    Every exit path writes exactly one ``tool_executions`` row so the
    audit trail is complete regardless of which step failed.

    Returns a :class:`_PerToolResult`. Lookup / validation / execute
    failures are reported via ``error_code`` so :func:`asyncio.gather`
    can collect every sibling's outcome rather than cancelling on the
    first raise.
    """
    tool_name = getattr(block, "name", "") or ""
    tool_use_id = getattr(block, "id", "") or ""
    raw_input = getattr(block, "input", None)
    input_payload = raw_input if isinstance(raw_input, dict) else {}

    # Registry lookup. ``KeyError`` here means Claude called a tool
    # that wasn't registered — wiring bug, not user-facing fault.
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

    # Input validation. Surface as terminal ``validation_error`` per
    # SEV-495 acceptance criteria — the tool framework guarantees
    # ``execute`` only ever sees a well-typed ``Input`` instance.
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

    # Wrap the wire emitter so we can detect whether the tool itself
    # already announced its UI block via ``BlockStart`` (incremental
    # streaming — C1.4) or whether the loop must do it (non-incremental
    # case where the tool only returns the final block). Each per-tool
    # coroutine owns its own ``_RecordingEmitter``: the recording is
    # local to this tool, while the underlying ``sse_emitter`` is shared
    # — sibling tools' events interleave on the wire (block IDs are
    # independent so iOS still correlates).
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
        # Tool-side failures are ``TOOL_ERROR`` regardless of the
        # underlying exception type — that's the band of error
        # codes reserved for "the tool itself raised". Anthropic-
        # adjacent failures only surface when the loop calls
        # Anthropic, not when a tool runs.
        return _PerToolResult(
            tool_result_block=None,
            ui_block_dict=None,
            counted=False,
            error_code=ErrorCode.TOOL_ERROR,
        )
    tool_latency_ms = int((time.monotonic() - tool_started) * 1000)

    # Drive the wire envelope for any UI block returned. The tool
    # may have already emitted ``block_start`` (and ``block_data``
    # patches) inline; if so we only emit ``block_end``. Otherwise
    # we emit ``block_start`` with the final block + ``block_end``.
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

    # Persist the audit row. Per the AI v0 plan, ``ui_blocks_emitted``
    # is the merged final state — not a per-patch log.
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
    # text/image blocks. JSON-encode the model payload so any shape
    # roundtrips cleanly without dropping the structure.
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
    """Process every ``tool_use`` block in an Anthropic response **in parallel**.

    Anthropic emits multiple ``tool_use`` blocks in one response when the
    model judges the calls independent (e.g. ``get_stock_info("AAPL")``
    plus ``get_stock_info("MSFT")``). SEV-565: dispatch them concurrently
    via :func:`asyncio.gather` so wall-clock latency is ``max(t_i)`` rather
    than ``sum(t_i)``.

    Ordering: results are aggregated in tool_use input order, so
    ``tool_result_blocks`` and ``ui_block_dicts`` match the order Anthropic
    emitted (and the order persisted on ``model_invocations.response_content``).
    Wire-level ``BlockStart`` / ``BlockEnd`` events for sibling tools may
    interleave — block IDs are independent so iOS correlates per-block
    ``text_delta`` / ``block_data`` patches by ID, not arrival order
    (see ``ConversationStore.handle`` on the iOS side). The iOS block
    *array* order on streaming follows ``BlockStart`` arrival, while
    the persisted ``messages.content_blocks`` array is in tool_use input
    order — a divergence that is only observable across a reload of an
    incomplete render and acceptable for v0.

    Error semantics: every ``tool_use`` block writes its ``tool_executions``
    row regardless of which sibling succeeded or failed (audit-row
    completeness wins over early termination). After ``gather`` returns
    the aggregator picks the **first** error in input order as the
    iteration's ``terminal_error_code``.
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
    # Default gather (no ``return_exceptions``): per-tool coroutines
    # catch their own lookup/validation/execute failures and report
    # them via ``_PerToolResult.error_code``. A coroutine raising out
    # is a programming bug (e.g. DB write failed) — propagate so the
    # outer loop's ``except Exception`` maps it to INTERNAL_ERROR.
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
) -> AgentTurnResult:
    """Run one agent turn end-to-end.

    Returns an :class:`AgentTurnResult` describing the terminal state, the
    user-facing assistant blocks, total cost, and iteration count. The
    function does not raise on Anthropic errors — those are caught,
    mapped to an :class:`ErrorCode` and persisted on ``agent_turns`` with
    ``terminal_state='error'``. ``asyncio.CancelledError`` propagates after
    the in-progress audit rows are flushed. B3.4 layers partial-state
    persistence on top of that contract: when cancellation lands while a
    text block is mid-stream, the loop closes the upstream connection,
    captures whatever text accumulated, and writes it to
    ``messages.content_blocks`` alongside ``agent_turns.terminal_state =
    'cancelled'`` / ``cancellation_reason``. The ``CancelledError`` is
    always re-raised after persistence.

    The conversation row at ``conversation_id`` must already exist (the
    endpoint creates it on first turn per decision D6).

    Raises ``ValueError`` if ``hard_caps.max_output_tokens`` is not strictly
    greater than the thinking budget — Anthropic 400s on every call when
    ``budget_tokens >= max_tokens``. Fails fast before any DB writes (and
    before any SSE event is emitted) so a misconfigured cap can't leave
    half-written audit rows or a stranded ``turn_started`` frame.

    SSE wire (B2.4): once ``agent_turns.id`` is known the loop emits
    ``turn_started`` on ``sse_emitter``. Each text block streamed by
    Anthropic produces ``block_start`` (with a server-assigned ULID
    ``block_id``) → one ``text_delta`` per chunk → ``block_end``. Thinking
    and tool-use blocks stay server-side. The loop closes with
    ``turn_completed`` on success, or ``error`` on cap breach / Anthropic
    failure. **The loop only guarantees a terminal frame for normal exit
    paths** (cap breach, Anthropic error trapped in the inner ``except
    Exception``, or any of the ``stop_reason`` branches). Anything
    escaping as an unhandled ``Exception`` or ``BaseException`` reaches
    the caller without a terminal frame — the chat-turn endpoint's
    ``_drive_turn`` catches non-``CancelledError`` exceptions and emits
    its own ``error`` so iOS isn't left hanging; ``CancelledError``
    means the client already disconnected so the missing terminal
    frame is never observed.

    Langfuse instrumentation (A3.2): the entire turn is wrapped in an
    ``agent`` observation whose trace_id is ``agent_turn.id.hex`` so the
    Postgres ``agent_turns`` row and the Langfuse trace cross-reference
    on the bare turn UUID. Trace-level tags (``user_id``,
    ``conversation_id``, ``turn_id``, ``prompt_hash``, ``environment``,
    ``model_id``) are set via ``propagate_attributes`` so they apply to
    every child observation in the trace. Each Anthropic call is its own
    ``generation`` observation with input/output captured verbatim. A3.3
    extends the generation update with ``usage_details`` (per-bucket token
    counts including the thinking estimate) and ``cost_details`` (total
    USD from :func:`cost_usd_micros`), so Langfuse Cloud aggregates cost
    per turn and shows the token breakdown.

    Cancellation (B3.3): the entire function body runs inside a single
    outer ``try / except CancelledError / finally`` so a cancellation
    landing at *any* await — early DB writes, the ``turn_started`` SSE
    emit, langfuse setup, or anywhere inside the loop — still finalises
    the agent_turn row instead of leaving it stuck in non-terminal state.
    On CancelledError the outer ``except`` sets
    ``terminal_state='cancelled'`` (if not already set by the inner
    handler) and ``error_code=CANCELLED``, then the outer ``finally``
    persists the row via :meth:`ConversationRepository.complete_agent_turn`
    (when ``turn_id`` exists — i.e. ``start_agent_turn`` already ran).
    The CancelledError re-propagates to the caller after the audit row
    is durable.

    ``disconnect_check`` is an optional polling hook left in place for
    unit-test ergonomics and for future wiring to a real disconnect
    signal. It is **not** wired to ``request.is_disconnected`` in
    production: ``BaseHTTPMiddleware``-based middleware (this codebase's
    auth / logging / correlation / rate-limit chain) consumes the ASGI
    receive channel upstream of the route, so the route's
    ``request.is_disconnected`` never fires. Production cancellation is
    driven instead by the framework's external ``task.cancel()`` when the
    SSE asyncgen is closed, which lands as a CancelledError at whatever
    await the loop is currently in — handled by the same outer except.

    No terminal SSE frame is emitted on cancellation since the client
    connection that would consume it is gone.
    """
    if hard_caps.max_output_tokens <= _THINKING_BUDGET_TOKENS:
        raise ValueError(
            f"hard_caps.max_output_tokens ({hard_caps.max_output_tokens}) "
            f"must be > thinking budget ({_THINKING_BUDGET_TOKENS}); "
            f"Anthropic requires budget_tokens < max_tokens."
        )

    # State that the outer ``finally`` reads. Initialised before the first
    # await so a CancelledError landing at *any* await — including the
    # very first DB write — still finds well-defined values when the
    # finally runs the audit-row write. ``turn_id`` stays None until
    # ``start_agent_turn`` succeeds; the finally guards on it so we never
    # try to finalise a row that was never opened.
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
    # B3.4: populated when the loop catches ``CancelledError``. Persisted
    # on ``agent_turns.cancellation_reason`` so the audit row distinguishes
    # client disconnects from internal errors.
    cancellation_reason: str | None = None
    # ``True`` only after the while loop exits via a ``break`` (not an
    # exception). Used in the finally block to gate the terminal SSE frame
    # — unexpected exceptions reach the caller, which surfaces them.
    completed_normally = False

    try:
        # 1. Persist the user message before anything else so a crash mid-turn
        #    still leaves the user's input recorded. Mint a ``block_id`` so the
        #    persisted shape matches assistant text blocks (which always carry
        #    one via the SSE accumulator). Without it the iOS resume decoder
        #    drops the block and the user bubble renders empty (SEV-564).
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

        # 2. Load full history (includes the just-persisted user message) and
        #    transform into the Anthropic messages array shape. Persisted blocks
        #    pass through ``_to_anthropic_content`` to drop Sevino-only fields
        #    (``block_id`` on text blocks) before they re-enter the API.
        async with db_factory() as db:
            history = await ConversationRepository.load_history(db, conversation_id)
        messages: list[dict[str, Any]] = [
            {"role": m.role, "content": _to_anthropic_content(m.content_blocks)}
            for m in history
        ]

        # 3. Open the agent_turn row. From here, the outer finally block
        #    guarantees a completion call so the row never sits in a
        #    non-terminal state — even if cancellation lands during the
        #    ``turn_started`` emit, langfuse setup, or any await inside the
        #    loop.
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

        # 4. SSE: announce the turn now that the row is durable. ``turn_id``
        #    here is the same UUID iOS sees on subsequent ``turn_completed`` /
        #    ``error`` frames and the same value persisted on ``agent_turns.id``.
        await sse_emitter.emit(
            TurnStarted(turn_id=turn_id, conversation_id=conversation_id)
        )

        # Per A1.8: mark the system block as a cache breakpoint. Anthropic caches
        # everything up to the marker, so the system prompt is reused across turns
        # within the 5m TTL — input cost drops to the cache-read rate on hits.
        request_system: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": system_prompt.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # turn_id is a v4 UUID; .hex is the 32-char lowercase form Langfuse (W3C
        # trace context) requires. Using it verbatim means a Langfuse trace can
        # be looked up directly with the ``agent_turns.id`` value (no separate
        # langfuse_trace_id column needed).
        trace_context = {"trace_id": turn_id.hex}

        with langfuse.start_as_current_observation(
            as_type="agent",
            name="agent_turn",
            trace_context=trace_context,
            input={"user_message": user_message},
        ) as turn_span:
            # propagate_attributes must be entered AFTER the outer span so the
            # span is the active OTel span when attributes are set; otherwise the
            # tags don't reach the trace. Per the SDK docstring this is the
            # canonical path for trace-level user_id/session_id/tags/metadata.
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
                try:
                    while True:
                        # B3.3: poll for client disconnect at the iteration
                        # boundary before doing any further work. Self-raising
                        # CancelledError (rather than awaiting an external
                        # ``task.cancel()``) lets the ``except`` clause below
                        # set ``terminal_state='cancelled'`` deterministically
                        # — the audit row distinguishes a client disconnect
                        # from any other CancelledError.
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
                        # Anthropic 400s on an empty tools array, so omit the key
                        # entirely when no tools are registered (the v0 case). Per
                        # A1.8: mark the last tool with cache_control so the
                        # entire tools array is cached together with the system
                        # prompt.
                        if not tool_registry.is_empty:
                            tools_spec = list(tool_registry.to_anthropic_spec())
                            tools_spec[-1] = {
                                **tools_spec[-1],
                                "cache_control": {"type": "ephemeral"},
                            }
                            create_kwargs["tools"] = tools_spec

                        # Pass a shallow copy of ``messages`` so the captured
                        # input reflects the request as it was sent — the loop
                        # appends the assistant response to ``messages`` after
                        # the call, and Langfuse otherwise sees the mutated list.
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
                            # Maps Anthropic's ``index`` for an in-flight TEXT
                            # block to the server-assigned wire-level block_id.
                            # Only text blocks land here — thinking / tool_use
                            # are not user-facing in v0 so they don't get
                            # ``block_start`` / ``block_end`` events.
                            open_text_blocks: dict[int, str] = {}
                            # B3.3: counts text_deltas seen this iteration so
                            # ``disconnect_check`` polls on a fixed cadence
                            # rather than once per chunk (every chunk would be
                            # a hot-path ASGI-receive call).
                            text_deltas_seen = 0
                            # B3.4: parallel map of accumulated delta text per
                            # in-flight text block. On mid-stream cancellation
                            # this is the only record of what reached the wire,
                            # since ``stream.get_final_message()`` never
                            # returns — the iteration's ``response.content``
                            # path that normally populates ``assistant_blocks``
                            # is unreachable.
                            accumulated_text: dict[int, str] = {}
                            try:
                                async with anthropic_client.messages.stream(
                                    **create_kwargs
                                ) as stream:
                                    try:
                                        async for chunk in stream:
                                            if chunk.type == "content_block_start":
                                                if chunk.content_block.type == "text":
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
                                                    # B3.3: poll for disconnect on
                                                    # the cadence so a mid-response
                                                    # iOS close cancels the in-flight
                                                    # stream within a few hundred ms
                                                    # rather than running to
                                                    # completion. CancelledError
                                                    # raised here unwinds through
                                                    # the stream's ``async with``
                                                    # (closing the upstream HTTP
                                                    # connection) and lands in the
                                                    # inner ``except`` below, which
                                                    # captures partials per B3.4.
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
                                        response = await stream.get_final_message()
                                    except asyncio.CancelledError:
                                        # B3.4: mid-stream cancellation. Close
                                        # the upstream connection eagerly (the
                                        # ``async with`` would also call close
                                        # on exit, but doing it here keeps the
                                        # semantics explicit: the upstream
                                        # request is released BEFORE we touch
                                        # any DB writes in the outer finally).
                                        # Then capture each open text block's
                                        # accumulated text into ``assistant_blocks``
                                        # so ``messages.content_blocks`` records
                                        # what iOS already saw on the wire.
                                        # Empty blocks are skipped — a
                                        # ``BlockStart`` with no deltas yields
                                        # no user-visible text.
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
                                        gen.update(
                                            level="WARNING",
                                            status_message="cancelled",
                                        )
                                        raise
                            except Exception as exc:
                                error_code = to_error_code(exc)
                                terminal_state = "error"
                                # The exception is caught (loop never raises), so
                                # the generation span would otherwise exit cleanly.
                                # Tag it explicitly so Langfuse marks the gen as
                                # failed.
                                gen.update(
                                    level="ERROR",
                                    status_message=f"{type(exc).__name__}: {exc}",
                                )
                                break
                            latency_ms = int((time.monotonic() - iter_started) * 1000)

                            # Anthropic content for the next iteration's request
                            # and for ``model_invocations.response_content`` (the
                            # source of truth A1.7's thinking signature
                            # roundtripping reads from). ``scrub_blocks`` strips
                            # SDK-only fields like ``parsed_output`` / ``citations``
                            # / ``caller``; Anthropic accepts them on output but
                            # 400s when they re-appear as input on iteration N+1.
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
                            # A3.3: ingest usage + cost on the generation so the
                            # Langfuse trace shows USD per turn and the token
                            # breakdown. ``thinking`` is reported as our heuristic
                            # estimate from the visible thinking text — Anthropic
                            # bundles thinking tokens into ``output_tokens`` and
                            # bills them at the output rate, so ``cost_details``
                            # is a single ``total`` (no per-bucket split). We set
                            # ``total`` explicitly to ``input + output +
                            # cache_read + cache_creation``; ``thinking`` is
                            # omitted because it is already accounted for inside
                            # ``output_tokens``, and without an explicit ``total``
                            # Langfuse would auto-sum every bucket and inflate the
                            # per-trace count.
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

                        # User-facing blocks: only ``text`` blocks land in
                        # messages.content_blocks for v0. Thinking, tool_use, and
                        # future block types are excluded — A1.7 keeps thinking
                        # server-side and Phase 3 introduces the StatusBlock /
                        # StockCardBlock pipeline. The block_id reuses the ULID
                        # already emitted on ``block_start`` so iOS can correlate
                        # the persisted block back to the streamed events.
                        for index, block in enumerate(response.content):
                            if block.type == "text":
                                block_id = open_text_blocks.get(index)
                                if block_id is None:
                                    # Fallback: mint a fresh ULID so the JSONB
                                    # schema stays valid. The persisted block_id
                                    # won't match any streamed ``block_start``,
                                    # so iOS correlation breaks — log loudly so
                                    # the desync surfaces in observability.
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

                        if response.stop_reason == "end_turn":
                            terminal_state = "end_turn"
                            break
                        if response.stop_reason == "max_tokens":
                            terminal_state = "output_token_limit"
                            error_code = ErrorCode.OUTPUT_TOKEN_LIMIT
                            break
                        if response.stop_reason == "tool_use":
                            # C1.2 / C1.4 / SEV-565: parallel tool dispatch.
                            # See :func:`_dispatch_tool_uses` for the
                            # ``asyncio.gather`` machinery and
                            # :func:`_dispatch_one_tool_use` for per-block
                            # registry lookup / validation / execute /
                            # audit-row / wire-event semantics.
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
                            # Defensive: ``stop_reason == "tool_use"`` with
                            # no ``tool_use`` blocks in the response is an
                            # Anthropic contract violation we never expect
                            # to see. Treat as ``INTERNAL_ERROR`` rather
                            # than looping forever appending an empty user
                            # message.
                            if tool_outcomes.tool_call_count == 0:
                                terminal_state = "error"
                                error_code = ErrorCode.INTERNAL_ERROR
                                break
                            assistant_blocks.extend(
                                tool_outcomes.ui_block_dicts
                            )
                            state.tool_calls += tool_outcomes.tool_call_count
                            # Anthropic expects the tool_result blocks to
                            # ride on a follow-up ``user`` message —
                            # stop_reason on the next iteration drives
                            # whether Claude needs another tool round or
                            # finally returns text.
                            messages.append(
                                {
                                    "role": "user",
                                    "content": tool_outcomes.tool_result_blocks,
                                }
                            )
                            continue
                        if response.stop_reason == "pause_turn":
                            # Anthropic paused a long-running turn (typically mid
                            # extended-thinking). Per the API contract we continue
                            # by passing the response content back as-is — already
                            # appended to ``messages`` above, so the next
                            # iteration's request will roundtrip the iteration-N
                            # thinking block with its signature intact (A1.7
                            # requirement R1). The cap check at the top of the
                            # next iteration enforces wall-clock / iteration /
                            # output-token bounds.
                            continue
                        # Any other stop reason (refusal, stop_sequence, etc.) —
                        # record verbatim so the audit row carries the real signal.
                        terminal_state = response.stop_reason or "unknown"
                        break
                    # Reached only via a normal break — used below to gate the
                    # terminal SSE frame.
                    completed_normally = True
                except asyncio.CancelledError:
                    # B3.3 / B3.4: cancellation landed inside the loop.
                    # Either our ``disconnect_check`` poll raised it, the
                    # innermost streaming handler re-raised after
                    # capturing partial text (B3.4), or the framework
                    # cancelled the task externally. Set
                    # ``terminal_state='cancelled'`` plus
                    # ``cancellation_reason`` so the inner finally tags
                    # the langfuse span and the outer finally persists
                    # the audit row with both fields populated.
                    terminal_state = "cancelled"
                    error_code = ErrorCode.CANCELLED
                    cancellation_reason = _DEFAULT_CANCELLATION_REASON
                    raise
                finally:
                    # Inner finally: just update the langfuse turn span — the
                    # span needs to be the active OTel span when ``update``
                    # is called, so it can't move to the outer finally
                    # (which runs after both ``with`` blocks have exited).
                    # Defensive guard for terminal_state=None handles the
                    # rare case of a non-CancelledError, non-Exception
                    # control-flow exit (BaseException, SystemExit) so
                    # Langfuse always gets coherent values.
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
        # B3.3 outer catch: cancellation landed BEFORE the inner try block —
        # i.e. during user-message persistence, history load,
        # ``start_agent_turn``, ``turn_started`` emit, langfuse span entry,
        # or ``propagate_attributes`` setup. The outer ``finally`` below
        # still runs and persists the agent_turn row (if it was opened)
        # with ``terminal_state='cancelled'``. Without this clause, the
        # framework's external ``task.cancel()`` would land on one of the
        # early DB awaits and leave the row stuck in non-terminal state
        # forever. ``raise`` re-propagates so the caller still sees
        # CancelledError.
        if terminal_state is None:
            terminal_state = "cancelled"
            error_code = ErrorCode.CANCELLED
        # B3.4: populate the reason regardless of which handler set the
        # terminal state — the inner streaming handler raises through
        # this clause too.
        if cancellation_reason is None:
            cancellation_reason = _DEFAULT_CANCELLATION_REASON
        raise
    finally:
        # Defensive: a non-CancelledError exception escaped without setting
        # terminal_state. Mark it as an error so the row never sits in
        # non-terminal state.
        if terminal_state is None:
            terminal_state = "error"
            error_code = ErrorCode.INTERNAL_ERROR

        # If ``start_agent_turn`` never ran (cancellation/error during
        # user-message persist or history load), there is no agent_turn
        # row to finalise — the user_message row is durable on its own.
        #
        # Route the writes through ``asyncio.shield`` so they survive even
        # when the parent task is cancelled mid-finally (observed under
        # sse-starlette's task-group teardown on client disconnect: the
        # raw await inside the finally was getting re-cancelled before
        # COMMIT). ``shield`` runs the helper in a child task whose
        # cancel scope is independent of the parent — when the parent
        # gets a CancelledError while waiting on shield, the parent
        # propagates but the child keeps running on the event loop and
        # writes the row.
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

        # Terminal SSE frame: only when the loop exited via its own
        # break paths. If an unhandled exception is propagating, the
        # caller surfaces it as ``error`` — emitting here would race
        # with that and produce two terminal frames on the wire.
        # ``turn_id is not None`` is implied by ``completed_normally``
        # but kept explicit for the type checker.
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

    # Reachable only when the loop exited via a normal break — every
    # cancellation / exception path re-raises through the outer except,
    # which means turn_id was set before the loop ran.
    assert turn_id is not None
    return AgentTurnResult(
        turn_id=turn_id,
        terminal_state=terminal_state,
        assistant_message_blocks=assistant_blocks,
        total_cost_usd_micros=totals["cost"],
        iterations_count=state.iterations,
    )
