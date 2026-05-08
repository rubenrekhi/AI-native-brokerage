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

import time
import uuid
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from langfuse import propagate_attributes
from ulid import ULID

from app.ai.observability.langfuse import LangfuseClient
from app.ai.prompts import SystemPrompt
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
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Error,
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
    """
    converted: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "text":
            converted.append(
                {"type": "text", "text": block.get("text", "")}
            )
        else:
            # Non-text blocks are reserved for future variants (StatusBlock,
            # StockCardBlock). When those land they may need their own
            # filtering — pass through for now so the discriminator catches
            # any premature use during development.
            converted.append(block)
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


async def run_agent_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
    anthropic_client: AsyncAnthropic,
    db_factory: DbSessionFactory,
    tool_registry: ToolRegistry,
    system_prompt: SystemPrompt,
    model_config: ModelConfig,
    hard_caps: HardCaps,
    langfuse: LangfuseClient,
    environment: str,
    sse_emitter: SSEEmitter,
) -> AgentTurnResult:
    """Run one agent turn end-to-end.

    Returns an :class:`AgentTurnResult` describing the terminal state, the
    user-facing assistant blocks, total cost, and iteration count. The
    function does not raise on Anthropic errors — those are caught,
    mapped to an :class:`ErrorCode` and persisted on ``agent_turns`` with
    ``terminal_state='error'``. ``asyncio.CancelledError`` propagates after
    the in-progress audit rows are flushed.

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
    """
    if hard_caps.max_output_tokens <= _THINKING_BUDGET_TOKENS:
        raise ValueError(
            f"hard_caps.max_output_tokens ({hard_caps.max_output_tokens}) "
            f"must be > thinking budget ({_THINKING_BUDGET_TOKENS}); "
            f"Anthropic requires budget_tokens < max_tokens."
        )

    # 1. Persist the user message before anything else so a crash mid-turn
    #    still leaves the user's input recorded.
    async with db_factory() as db:
        user_msg = await ConversationRepository.append_user_message(
            db,
            conversation_id=conversation_id,
            content_blocks=[{"type": "text", "text": user_message}],
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

    # 3. Open the agent_turn row. From here, the finally block guarantees a
    #    completion call so the row never sits in a non-terminal state.
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
    # ``True`` only after the while loop exits via a ``break`` (not an
    # exception). Used in the finally block to gate the terminal SSE frame
    # — unexpected exceptions reach the caller, which surfaces them.
    completed_normally = False

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
                        try:
                            async with anthropic_client.messages.stream(
                                **create_kwargs
                            ) as stream:
                                async for chunk in stream:
                                    if chunk.type == "content_block_start":
                                        if chunk.content_block.type == "text":
                                            block_id = str(ULID())
                                            open_text_blocks[chunk.index] = (
                                                block_id
                                            )
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
                                            await sse_emitter.emit(
                                                TextDelta(
                                                    block_id=open_text_blocks[
                                                        chunk.index
                                                    ],
                                                    text=chunk.delta.text,
                                                )
                                            )
                                    elif chunk.type == "content_block_stop":
                                        block_id = open_text_blocks.get(
                                            chunk.index
                                        )
                                        if block_id is not None:
                                            await sse_emitter.emit(
                                                BlockEnd(block_id=block_id)
                                            )
                                response = await stream.get_final_message()
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

                        # Verbatim Anthropic content for the next iteration's
                        # request and for model_invocations.response_content.
                        # The JSONB column is the source of truth that A1.7's
                        # thinking signature roundtripping reads from.
                        response_content = [
                            block.model_dump(mode="json")
                            for block in response.content
                        ]
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
                        # Unreachable in v0 (no tools registered). If reached,
                        # the tool framework is misconfigured — treat as
                        # internal error.
                        terminal_state = "error"
                        error_code = ErrorCode.INTERNAL_ERROR
                        break
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
            finally:
                # Defensive: every loop exit path above sets terminal_state.
                # This guards against future refactors leaving an unexpected
                # branch.
                if terminal_state is None:
                    terminal_state = "error"
                    error_code = ErrorCode.INTERNAL_ERROR

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
                        error_code=(
                            error_code.value if error_code is not None else None
                        ),
                        iterations_count=state.iterations,
                        total_input_tokens=totals["input"],
                        total_output_tokens=totals["output"],
                        total_cache_read_tokens=totals["cache_read"],
                        total_cache_creation_tokens=totals["cache_creation"],
                        total_thinking_tokens=totals["thinking"],
                        total_cost_usd_micros=totals["cost"],
                    )

                turn_span.update(
                    output={
                        "terminal_state": terminal_state,
                        "iterations": state.iterations,
                        "assistant_blocks": assistant_blocks,
                    },
                    level="ERROR" if error_code is not None else "DEFAULT",
                    status_message=(
                        error_code.value if error_code is not None else None
                    ),
                )

                # Terminal SSE frame: only when the loop exited via its own
                # break paths. If an unhandled exception is propagating, the
                # caller surfaces it as ``error`` — emitting here would race
                # with that and produce two terminal frames on the wire.
                if completed_normally:
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

    return AgentTurnResult(
        turn_id=turn_id,
        terminal_state=terminal_state,
        assistant_message_blocks=assistant_blocks,
        total_cost_usd_micros=totals["cost"],
        iterations_count=state.iterations,
    )
