"""Single-iteration body of the agent loop.

One iteration is: build the request → stream the response → persist the
model invocation → reconcile server tools → accumulate totals → route by
``stop_reason``. The outer :func:`~app.ai.runtime.loop.run_agent_turn`
keeps the per-iteration cap check, disconnect poll, and terminal
finalization.

:func:`run_one_iteration` returns an :class:`IterationOutcome` telling
the caller whether to ``continue`` or ``break`` and, if breaking, the
``terminal_state`` / ``error_code`` to record.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message
from ulid import ULID

from app.ai.observability.langfuse import LangfuseClient
from app.ai.runtime.anthropic_io import (
    estimate_thinking_tokens,
    scrub_blocks,
)
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.cost import cost_usd_micros
from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.errors import ErrorCode, to_error_code
from app.ai.runtime.dispatch.custom import dispatch_tool_uses
from app.ai.runtime.dispatch.server import (
    ServerToolTracker,
    append_status_blocks_for_persistence,
    build_server_tool_specs,
)
from app.ai.runtime.flow.stream_consumer import StreamConsumer
from app.ai.runtime.flow.turn_lifecycle import TurnTotals
from app.ai.runtime.types import (
    LoopState,
    ModelConfig,
    ServerToolsConfig,
    ToolRegistry,
)
from app.ai.tools.base import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.repositories.conversation import ConversationRepository

__all__ = [
    "IterationOutcome",
    "build_iteration_request",
    "run_one_iteration",
]

logger = structlog.get_logger(__name__)

# Anthropic requires ``budget_tokens >= 1024`` and ``< max_tokens``.
_THINKING_BUDGET_TOKENS = 1024


@dataclass(slots=True)
class IterationOutcome:
    """Decision the loop acts on after one iteration completes.

    ``action == "continue"`` → loop another iteration.
    ``action == "break"`` → exit with ``terminal_state`` and optional
    ``error_code``. ``invocation_id`` is the row id of the last successful
    model invocation, needed by the orphan flush.
    """

    action: str
    terminal_state: str | None = None
    error_code: ErrorCode | None = None
    invocation_id: uuid.UUID | None = None


def build_iteration_request(
    *,
    model_config: ModelConfig,
    hard_caps: HardCaps,
    request_system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tool_registry: ToolRegistry,
    server_tools_config: ServerToolsConfig,
) -> dict[str, Any]:
    """Build the ``anthropic.messages.stream`` kwargs for one iteration.

    Server tools and registry tools are concatenated. ``cache_control``
    on the last tool spec caches the tools array alongside the system
    prompt, so the cache window covers both across iterations.
    """
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
    # Anthropic 400s on empty tools.
    server_tool_specs = build_server_tool_specs(server_tools_config)
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
    return create_kwargs


async def _decide_after_response(
    *,
    response: Message,
    invocation_id: uuid.UUID,
    state: LoopState,
    messages: list[dict[str, Any]],
    assistant_blocks: list[dict[str, Any]],
    tool_registry: ToolRegistry,
    user_id: uuid.UUID,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
) -> IterationOutcome:
    stop_reason = response.stop_reason
    if stop_reason == "end_turn":
        return IterationOutcome(
            action="break",
            terminal_state="end_turn",
            invocation_id=invocation_id,
        )
    if stop_reason == "max_tokens":
        return IterationOutcome(
            action="break",
            terminal_state="output_token_limit",
            error_code=ErrorCode.OUTPUT_TOKEN_LIMIT,
            invocation_id=invocation_id,
        )
    if stop_reason == "tool_use":
        tool_outcomes = await dispatch_tool_uses(
            response_blocks=response.content,
            tool_registry=tool_registry,
            user_id=user_id,
            db_factory=db_factory,
            sse_emitter=sse_emitter,
            http_clients=http_clients,
            invocation_id=invocation_id,
        )
        if tool_outcomes.terminal_error_code is not None:
            assistant_blocks.extend(tool_outcomes.ui_block_dicts)
            return IterationOutcome(
                action="break",
                terminal_state="error",
                error_code=tool_outcomes.terminal_error_code,
                invocation_id=invocation_id,
            )
        # ``tool_use`` stop with no tool_use blocks would loop forever — fail it.
        if tool_outcomes.tool_call_count == 0:
            return IterationOutcome(
                action="break",
                terminal_state="error",
                error_code=ErrorCode.INTERNAL_ERROR,
                invocation_id=invocation_id,
            )
        assistant_blocks.extend(tool_outcomes.ui_block_dicts)
        state.tool_calls += tool_outcomes.tool_call_count
        # Anthropic expects tool_results on a follow-up ``user`` message.
        messages.append(
            {"role": "user", "content": tool_outcomes.tool_result_blocks}
        )
        return IterationOutcome(action="continue", invocation_id=invocation_id)
    if stop_reason == "pause_turn":
        # Continue verbatim — already appended to messages so signatures
        # roundtrip intact.
        return IterationOutcome(action="continue", invocation_id=invocation_id)
    # Refusal, stop_sequence, etc. — record verbatim.
    return IterationOutcome(
        action="break",
        terminal_state=stop_reason or "unknown",
        invocation_id=invocation_id,
    )


async def run_one_iteration(
    *,
    state: LoopState,
    request_system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    assistant_blocks: list[dict[str, Any]],
    totals: TurnTotals,
    model_config: ModelConfig,
    hard_caps: HardCaps,
    tool_registry: ToolRegistry,
    server_tools_config: ServerToolsConfig,
    server_tool_tracker: ServerToolTracker,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    turn_id: uuid.UUID,
    anthropic_client: AsyncAnthropic,
    db_factory: DbSessionFactory,
    sse_emitter: SSEEmitter,
    http_clients: ToolHttpClients,
    langfuse: LangfuseClient,
    disconnect_check: Callable[[], Awaitable[bool]] | None,
) -> IterationOutcome:
    iteration_index = state.iterations
    create_kwargs = build_iteration_request(
        model_config=model_config,
        hard_caps=hard_caps,
        request_system=request_system,
        messages=messages,
        tool_registry=tool_registry,
        server_tools_config=server_tools_config,
    )

    # Copy ``messages`` — the loop mutates it after the call, and Langfuse
    # would otherwise see the new state.
    with langfuse.start_as_current_observation(
        as_type="generation",
        name="anthropic.messages.create",
        model=model_config.model_id,
        input={"system": request_system, "messages": list(messages)},
        metadata={"iteration_index": iteration_index},
    ) as gen:
        iter_started = time.monotonic()
        consumer = StreamConsumer(
            sse_emitter=sse_emitter,
            server_tool_tracker=server_tool_tracker,
            server_tools_config=server_tools_config,
            disconnect_check=disconnect_check,
        )
        try:
            try:
                response = await consumer.consume(anthropic_client, create_kwargs)
            except asyncio.CancelledError:
                for index, block_id in consumer.open_text_blocks.items():
                    partial = consumer.accumulated_text.get(index, "")
                    if partial:
                        assistant_blocks.append(
                            {
                                "type": "text",
                                "block_id": block_id,
                                "text": partial,
                            }
                        )
                # On cancel text/pill interleaving is lost — pills land
                # after partial text.
                append_status_blocks_for_persistence(
                    tool_use_ids=list(
                        server_tool_tracker.status_block_records.keys()
                    ),
                    status_block_records=server_tool_tracker.status_block_records,
                    status_blocks_persisted=server_tool_tracker.status_blocks_persisted,
                    assistant_blocks=assistant_blocks,
                )
                gen.update(level="WARNING", status_message="cancelled")
                raise
        except Exception as exc:
            # We catch the exception, so tag the gen explicitly or
            # Langfuse will mark it OK.
            gen.update(
                level="ERROR",
                status_message=f"{type(exc).__name__}: {exc}",
            )
            return IterationOutcome(
                action="break",
                terminal_state="error",
                error_code=to_error_code(exc),
            )
        latency_ms = int((time.monotonic() - iter_started) * 1000)

        # ``scrub_blocks`` strips SDK-only fields the API accepts on
        # output but rejects as input.
        response_content = scrub_blocks(
            [block.model_dump(mode="json") for block in response.content]
        )
        cost = cost_usd_micros(response.usage, model_config.model_id)
        iter_thinking_tokens = estimate_thinking_tokens(response_content)
        cache_read = response.usage.cache_read_input_tokens or 0
        cache_create = response.usage.cache_creation_input_tokens or 0
        # Explicit ``total`` so Langfuse doesn't auto-sum and double-count
        # thinking (it's already in ``output_tokens``).
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
        invocation = await ConversationRepository.record_model_invocation(
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
        invocation_id = invocation.id

    if server_tools_config.any_enabled:
        await server_tool_tracker.record_executions(
            response_blocks=response.content,
            invocation_id=invocation_id,
            db_factory=db_factory,
            turn_id=turn_id,
            conversation_id=conversation_id,
        )

    state.iterations += 1
    state.output_tokens += response.usage.output_tokens
    totals.accumulate(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_read=cache_read,
        cache_creation=cache_create,
        thinking_tokens=iter_thinking_tokens,
        cost=cost,
    )

    messages.append({"role": "assistant", "content": response_content})

    # Preserve order so reload matches the live stream.
    for index, block in enumerate(response.content):
        if block.type == "text":
            block_id = consumer.open_text_blocks.get(index)
            if block_id is None:
                # Persisted block_id won't match any streamed block_start
                # — iOS correlation breaks; log loudly.
                block_id = str(ULID())
                logger.warning(
                    "loop_text_block_id_fallback",
                    turn_id=str(turn_id),
                    iteration_index=iteration_index,
                    response_index=index,
                    streamed_indices=sorted(consumer.open_text_blocks.keys()),
                )
            assistant_blocks.append(
                {"type": "text", "block_id": block_id, "text": block.text}
            )
        elif block.type == "server_tool_use":
            tool_use_id = getattr(block, "id", None)
            if isinstance(tool_use_id, str):
                append_status_blocks_for_persistence(
                    tool_use_ids=[tool_use_id],
                    status_block_records=server_tool_tracker.status_block_records,
                    status_blocks_persisted=server_tool_tracker.status_blocks_persisted,
                    assistant_blocks=assistant_blocks,
                )

    return await _decide_after_response(
        response=response,
        invocation_id=invocation_id,
        state=state,
        messages=messages,
        assistant_blocks=assistant_blocks,
        tool_registry=tool_registry,
        user_id=user_id,
        db_factory=db_factory,
        sse_emitter=sse_emitter,
        http_clients=http_clients,
    )
