"""Agent loop core.

Per AI v0 plan A1.6 (sevino-api/docs/ai-v0-plan.md): a pure async function
that runs one agent turn end-to-end. v0 has no tools, so the loop runs
exactly one Anthropic call per turn (``stop_reason == "end_turn"``
immediately) — but the loop is structured to handle multi-iteration tool
use without restructuring once Project C lands.

**No FastAPI imports.** All collaborators (Anthropic client, DB factory,
tool registry, system prompt, model config, hard caps) are passed in by
the caller (typically the chat-turn endpoint added in A1.9) so the same
function is reusable by sub-agents and trivially testable in isolation.

Persistence pattern (decision D12): the loop opens a fresh ``AsyncSession``
via ``db_factory`` for every write — user message, agent_turn start,
each model_invocation, assistant message, agent_turn complete. Audit rows
are durable mid-turn rather than batched at the end.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from anthropic import AsyncAnthropic

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
from app.repositories.conversation import ConversationRepository

# CapBreach values map onto ErrorCode values surfaced in the SSE error event
# (Phase 2). TIMEOUT has no clean counterpart — ErrorCode lacks a TURN_TIMEOUT
# variant — so it folds into INTERNAL_ERROR for now. Adding TURN_TIMEOUT is a
# one-line follow-up that should land alongside Phase 2's SSE error event so
# the new code is actually surfaced to clients.
_BREACH_TO_ERROR_CODE: dict[CapBreach, ErrorCode] = {
    CapBreach.ITERATION_LIMIT: ErrorCode.TURN_ITERATION_LIMIT,
    CapBreach.TOOL_CALL_LIMIT: ErrorCode.TOOL_CALL_LIMIT,
    CapBreach.OUTPUT_TOKEN_LIMIT: ErrorCode.OUTPUT_TOKEN_LIMIT,
    CapBreach.TIMEOUT: ErrorCode.INTERNAL_ERROR,
}


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
    """
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
    #    transform into the Anthropic messages array shape.
    async with db_factory() as db:
        history = await ConversationRepository.load_history(db, conversation_id)
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": m.content_blocks} for m in history
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

    state = LoopState(started_at_monotonic=time.monotonic())
    assistant_blocks: list[dict[str, Any]] = []
    totals = {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "cost": 0,
    }
    terminal_state: str | None = None
    error_code: ErrorCode | None = None

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
            }
            # Anthropic 400s on an empty tools array, so omit the key
            # entirely when no tools are registered (the v0 case). Per A1.8:
            # mark the last tool with cache_control so the entire tools array
            # is cached together with the system prompt.
            if not tool_registry.is_empty:
                tools_spec = list(tool_registry.to_anthropic_spec())
                tools_spec[-1] = {
                    **tools_spec[-1],
                    "cache_control": {"type": "ephemeral"},
                }
                create_kwargs["tools"] = tools_spec

            iter_started = time.monotonic()
            try:
                response = await anthropic_client.messages.create(**create_kwargs)
            except Exception as exc:
                error_code = to_error_code(exc)
                terminal_state = "error"
                break
            latency_ms = int((time.monotonic() - iter_started) * 1000)

            cost = cost_usd_micros(response.usage, model_config.model_id)

            # Verbatim Anthropic content for the next iteration's request and
            # for the model_invocations.response_content audit column. The
            # JSONB column is the source of truth that A1.7's thinking
            # signature roundtripping reads from.
            response_content = [
                block.model_dump(mode="json") for block in response.content
            ]

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
                    cache_read_input_tokens=(
                        response.usage.cache_read_input_tokens or 0
                    ),
                    cache_creation_input_tokens=(
                        response.usage.cache_creation_input_tokens or 0
                    ),
                    cost_usd_micros=cost,
                    latency_ms=latency_ms,
                )

            state.iterations += 1
            state.output_tokens += response.usage.output_tokens
            totals["input"] += response.usage.input_tokens
            totals["output"] += response.usage.output_tokens
            totals["cache_read"] += response.usage.cache_read_input_tokens or 0
            totals["cache_creation"] += (
                response.usage.cache_creation_input_tokens or 0
            )
            totals["cost"] += cost

            messages.append({"role": "assistant", "content": response_content})

            # User-facing blocks: only ``text`` blocks land in
            # messages.content_blocks for v0. Thinking, tool_use, and future
            # block types are excluded — A1.7 keeps thinking server-side and
            # Phase 3 introduces the StatusBlock / StockCardBlock pipeline.
            for block in response.content:
                if block.type == "text":
                    assistant_blocks.append(
                        {"type": "text", "text": block.text}
                    )

            if response.stop_reason == "end_turn":
                terminal_state = "end_turn"
                break
            if response.stop_reason == "max_tokens":
                terminal_state = "output_token_limit"
                error_code = ErrorCode.OUTPUT_TOKEN_LIMIT
                break
            if response.stop_reason == "tool_use":
                # Unreachable in v0 (no tools registered). If reached, the
                # tool framework is misconfigured — treat as internal error.
                terminal_state = "error"
                error_code = ErrorCode.INTERNAL_ERROR
                break
            # Any other stop reason (pause_turn, refusal, etc.) — record
            # verbatim so the audit row carries the real signal.
            terminal_state = response.stop_reason or "unknown"
            break
    finally:
        # Defensive: every loop exit path above sets terminal_state. This
        # guards against future refactors leaving an unexpected branch.
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
                error_code=error_code.value if error_code is not None else None,
                iterations_count=state.iterations,
                total_input_tokens=totals["input"],
                total_output_tokens=totals["output"],
                total_cache_read_tokens=totals["cache_read"],
                total_cache_creation_tokens=totals["cache_creation"],
                total_thinking_tokens=0,
                total_cost_usd_micros=totals["cost"],
            )

    return AgentTurnResult(
        terminal_state=terminal_state,
        assistant_message_blocks=assistant_blocks,
        total_cost_usd_micros=totals["cost"],
        iterations_count=state.iterations,
    )
