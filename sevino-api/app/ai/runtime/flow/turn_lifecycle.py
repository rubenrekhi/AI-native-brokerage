"""Turn-level setup and teardown.

* :func:`initialize_turn` persists the user message, loads history, opens
  the ``agent_turns`` row, and emits the initial ``TurnStarted`` frame.
* :class:`TurnTotals` is the running counter across iterations.
* :func:`finalize_turn_row` writes the assistant message and closes the
  ``agent_turns`` row. Called via :func:`asyncio.shield` from the outer
  finally so cancellation can't truncate the COMMIT.
* :func:`emit_terminal_frame` sends the closing SSE event.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from ulid import ULID

from app.ai.context_blocks import ContextBlock, build_context_block
from app.ai.prompts import SystemPrompt
from app.ai.runtime.anthropic_io import to_anthropic_content
from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.types import ModelConfig
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import Error, TurnCompleted
from app.repositories.conversation import ConversationRepository
from app.schemas.conversations import AttachedContextRequest

__all__ = [
    "TurnTotals",
    "emit_terminal_frame",
    "finalize_turn_row",
    "initialize_turn",
]

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class TurnTotals:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    thinking: int = 0
    cost: int = 0

    def accumulate(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read: int,
        cache_creation: int,
        thinking_tokens: int,
        cost: int,
    ) -> None:
        self.input += input_tokens
        self.output += output_tokens
        self.cache_read += cache_read
        self.cache_creation += cache_creation
        self.thinking += thinking_tokens
        self.cost += cost


async def initialize_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
    user_context: AttachedContextRequest | None,
    system_prompt: SystemPrompt,
    model_config: ModelConfig,
    db_factory: DbSessionFactory,
) -> tuple[uuid.UUID, list[dict[str, Any]]]:
    """Persist the user message, load history, open the agent_turn row.

    Returns ``(turn_id, messages)``. The caller emits ``TurnStarted``
    *after* unpacking the tuple so a cancellation on that emit still
    leaves ``turn_id`` set in the outer scope — the outer finally relies
    on it to finalise the row.

    Persists the user message first so a crash mid-turn doesn't lose the
    user's input. ``block_id`` is required for the iOS resume decoder.

    An attached ``user_context`` drives two decoupled channels (SEV-615):
    the persisted ``ContextBlock`` (UI chip, restored on resume) and a
    short ``render_hint`` describing the open screen, appended to the current
    turn's messages (model input, this turn only). Only a whitelisted,
    non-stale field (the chart's selected range) is projected into the hint;
    the rest of ``data`` is never sent to the model, and the block is never
    replayed — ``to_anthropic_content`` drops it from history.
    """
    async with db_factory() as db:
        content_blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "block_id": str(ULID()),
                "text": user_message,
            }
        ]
        ctx_block: ContextBlock | None = None
        if user_context is not None:
            ctx_block = build_context_block(
                block_id=str(ULID()),
                kind=user_context.kind,
                data=user_context.data,
            )
            content_blocks.append(ctx_block.model_dump(mode="json"))
        user_msg = await ConversationRepository.append_user_message(
            db,
            conversation_id=conversation_id,
            content_blocks=content_blocks,
        )
        user_message_id = user_msg.id

    async with db_factory() as db:
        history = await ConversationRepository.load_history(db, conversation_id)
    messages: list[dict[str, Any]] = [
        {"role": m.role, "content": to_anthropic_content(m.content_blocks)}
        for m in history
    ]

    # Model channel, current turn only: build the attachment's hint and
    # append it to the just-persisted user message (``messages[-1]``). The
    # hint is ``kind``-driven and projects only a whitelisted ``data`` field.
    if ctx_block is not None:
        messages[-1]["content"].append(
            {"type": "text", "text": ctx_block.render_hint()}
        )

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

    return turn_id, messages


async def finalize_turn_row(
    db_factory: DbSessionFactory,
    *,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    terminal_state: str,
    error_code: ErrorCode | None,
    cancellation_reason: str | None,
    iterations_count: int,
    totals: TurnTotals,
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
                total_input_tokens=totals.input,
                total_output_tokens=totals.output,
                total_cache_read_tokens=totals.cache_read,
                total_cache_creation_tokens=totals.cache_creation,
                total_thinking_tokens=totals.thinking,
                total_cost_usd_micros=totals.cost,
            )
    except Exception:
        logger.exception(
            "agent_turn_finalize_failed",
            turn_id=str(turn_id),
            terminal_state=terminal_state,
        )


async def emit_terminal_frame(
    sse_emitter: SSEEmitter,
    *,
    turn_id: uuid.UUID,
    terminal_state: str,
    error_code: ErrorCode | None,
    totals: TurnTotals,
    iterations_count: int,
) -> None:
    if error_code is not None:
        await sse_emitter.emit(
            Error(code=error_code, message=f"terminal_state={terminal_state}")
        )
    else:
        await sse_emitter.emit(
            TurnCompleted(
                turn_id=turn_id,
                terminal_state=terminal_state,
                total_cost_usd_micros=totals.cost,
                iterations_count=iterations_count,
            )
        )
