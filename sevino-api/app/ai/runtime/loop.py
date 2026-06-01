"""Agent loop — runs one turn end-to-end.

Extended thinking is always enabled (1024-token budget). The loop iterates
on ``stop_reason == "pause_turn"``; prior thinking blocks are appended to
``messages`` before each call so signatures roundtrip byte-for-byte.

No FastAPI imports — collaborators are passed in so the same function
runs in sub-agents and unit tests.

The orchestrator lives here; per-turn execution (iteration body, stream
consumption, lifecycle setup/teardown) lives under
:mod:`app.ai.runtime.flow`, and tool dispatch (registered tools, hosted
server tools) lives under :mod:`app.ai.runtime.dispatch`.

Each write opens a fresh ``AsyncSession`` so audit rows are durable
mid-turn, not batched at the end.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

import structlog
from anthropic import AsyncAnthropic
from langfuse import propagate_attributes

from app.ai.observability.langfuse import LangfuseClient
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import CapBreach, HardCaps, check_caps
from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.dispatch.custom import (  # noqa: F401  (legacy test-compat re-export)
    ToolDispatchOutcome as _ToolDispatchOutcome,
)
from app.ai.runtime.dispatch.server import ServerToolTracker
from app.ai.runtime.flow.iteration import run_one_iteration
from app.ai.runtime.flow.turn_lifecycle import (
    TurnTotals,
    emit_terminal_frame,
    finalize_turn_row,
    initialize_turn,
)
from app.ai.runtime.types import (
    DISABLED_SERVER_TOOLS,
    AgentTurnResult,
    LoopState,
    ModelConfig,
    ServerToolsConfig,
    ToolRegistry,
)
from app.ai.tools.base import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import TurnStarted
from app.repositories.conversation import (  # noqa: F401  (patched class-wide via this module path)
    ConversationRepository,
)
from app.schemas.conversations import AttachedContextRequest, ContextKind

__all__ = ["run_agent_turn"]

logger = structlog.get_logger(__name__)

# TIMEOUT folds into INTERNAL_ERROR — no clean ErrorCode counterpart.
_BREACH_TO_ERROR_CODE: dict[CapBreach, ErrorCode] = {
    CapBreach.ITERATION_LIMIT: ErrorCode.TURN_ITERATION_LIMIT,
    CapBreach.TOOL_CALL_LIMIT: ErrorCode.TOOL_CALL_LIMIT,
    CapBreach.OUTPUT_TOKEN_LIMIT: ErrorCode.OUTPUT_TOKEN_LIMIT,
    CapBreach.TIMEOUT: ErrorCode.INTERNAL_ERROR,
}

_DEFAULT_CANCELLATION_REASON = "client_disconnect"


def _digest_card_context_source(
    digest_card: dict[str, Any] | None,
) -> dict[str, str | None] | None:
    """Derive the chat ``card_context_source`` ({symbol, kind}) from a digest
    card. Sourced from the unified ``context`` attachment (``kind=digest``);
    the card content reaches the model via ``DigestContextBlock.render_hint``,
    while this drives the client-side source chip on ``TurnStarted``."""
    if digest_card is None:
        return None

    kind = digest_card.get("kind")
    if not isinstance(kind, str) or not kind:
        return None

    symbol: str | None = None
    related_symbols = digest_card.get("related_symbols") or digest_card.get(
        "relatedSymbols"
    )
    if isinstance(related_symbols, list) and related_symbols:
        first_symbol = related_symbols[0]
        if isinstance(first_symbol, str) and first_symbol:
            symbol = first_symbol
    if symbol is None:
        raw_symbol = digest_card.get("symbol")
        if isinstance(raw_symbol, str) and raw_symbol:
            symbol = raw_symbol

    return {"symbol": symbol, "kind": kind}


async def run_agent_turn(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
    user_context: AttachedContextRequest | None = None,
    anthropic_client: AsyncAnthropic,
    db_factory: DbSessionFactory,
    tool_registry: ToolRegistry,
    system_prompt: SystemPrompt,
    time_context: str | None = None,
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

    ``time_context``, when provided, is appended to the current user message
    (via ``initialize_turn``) rather than the system prompt — so its live
    clock value sits after the conversation-history cache breakpoint and
    doesn't invalidate the cached prefix (prompt + tools + prior history).

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
    if hard_caps.max_output_tokens <= hard_caps.thinking_budget_tokens:
        raise ValueError(
            f"hard_caps.max_output_tokens ({hard_caps.max_output_tokens}) "
            f"must be > thinking budget ({hard_caps.thinking_budget_tokens}); "
            f"Anthropic requires budget_tokens < max_tokens."
        )

    # Initialised before the first await so the finally has well-defined
    # values even on early cancellation. The finally guards on ``turn_id``.
    turn_id: uuid.UUID | None = None
    state = LoopState(started_at_monotonic=time.monotonic())
    assistant_blocks: list[dict[str, Any]] = []
    totals = TurnTotals()
    terminal_state: str | None = None
    error_code: ErrorCode | None = None
    cancellation_reason: str | None = None
    # Gates the terminal SSE frame — only true after a normal break.
    completed_normally = False
    server_tool_tracker = ServerToolTracker()
    last_invocation_id: uuid.UUID | None = None

    try:
        turn_id, messages = await initialize_turn(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            user_context=user_context,
            system_prompt=system_prompt,
            model_config=model_config,
            db_factory=db_factory,
            time_context=time_context,
        )

        # Emitted here (not in ``initialize_turn``) so that a cancel on
        # this await still leaves ``turn_id`` set in the outer scope —
        # the outer finally relies on it to finalise the row. A digest
        # attachment (``context`` with ``kind=digest``) still drives the
        # client-side source chip; its card content reaches the model via
        # ``DigestContextBlock.render_hint`` (SEV-615), not the system prompt.
        digest_card = (
            user_context.data
            if user_context is not None
            and user_context.kind is ContextKind.DIGEST
            else None
        )
        await sse_emitter.emit(
            TurnStarted(
                turn_id=turn_id,
                conversation_id=conversation_id,
                card_context_source=_digest_card_context_source(digest_card),
            )
        )

        # Mark the system block as a cache breakpoint so Anthropic reuses
        # everything up to the marker across turns within the 5m TTL —
        # input cost drops to the cache-read rate on hits. The live clock +
        # market status is deliberately *not* here: it rides the current user
        # message (see ``initialize_turn``) so the per-turn timestamp stays
        # after the history breakpoint and never invalidates this prefix.
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

                        outcome = await run_one_iteration(
                            state=state,
                            request_system=request_system,
                            messages=messages,
                            assistant_blocks=assistant_blocks,
                            totals=totals,
                            model_config=model_config,
                            hard_caps=hard_caps,
                            tool_registry=tool_registry,
                            server_tools_config=server_tools_config,
                            server_tool_tracker=server_tool_tracker,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            anthropic_client=anthropic_client,
                            db_factory=db_factory,
                            sse_emitter=sse_emitter,
                            http_clients=http_clients,
                            langfuse=langfuse,
                            disconnect_check=disconnect_check,
                        )
                        if outcome.invocation_id is not None:
                            last_invocation_id = outcome.invocation_id
                        if outcome.action == "break":
                            terminal_state = outcome.terminal_state
                            error_code = outcome.error_code
                            break

                    # Close orphan server-tool uses so mid-turn errors
                    # don't leave pills stuck active.
                    if server_tools_config.any_enabled:
                        await server_tool_tracker.flush_orphans(
                            invocation_id=last_invocation_id,
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
                    server_tool_tracker.mark_active_failed()
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
                finalize_turn_row(
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
            await emit_terminal_frame(
                sse_emitter,
                turn_id=turn_id,
                terminal_state=terminal_state,
                error_code=error_code,
                totals=totals,
                iterations_count=state.iterations,
            )

    # Only reachable after a normal break.
    assert turn_id is not None
    return AgentTurnResult(
        turn_id=turn_id,
        terminal_state=terminal_state,
        assistant_message_blocks=assistant_blocks,
        total_cost_usd_micros=totals.cost,
        iterations_count=state.iterations,
    )
