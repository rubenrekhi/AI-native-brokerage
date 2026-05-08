"""Chat-turn endpoint.

Per AI v0 plan B2.3 (sevino-api/docs/ai-v0-plan.md): ``POST
/v1/conversations/{id}/turns`` returns ``text/event-stream``. The endpoint
creates an :class:`SSEEmitter`, spawns a task that runs the agent loop and
pushes wire events into the emitter, and yields those events to the
``EventSourceResponse``. URL and request body are unchanged from the
A1.9 JSON shape — only the response transport flips.

The driver task synthesises the wire envelope (``turn_started`` →
per-block ``block_start`` / ``text_delta`` / ``block_end`` →
``turn_completed``) from the eventual :class:`AgentTurnResult`. B2.4 will
move these emit calls inside ``run_agent_turn`` and add real per-token
streaming; the wire format is settled here so iOS (C3.1) can bind to it
without waiting on the loop change.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

import sentry_sdk
import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Request
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.ai.anthropic_client import get_anthropic
from app.ai.models import MODELS
from app.ai.observability.langfuse import LangfuseClient, get_langfuse
from app.ai.prompts import SYSTEM_PROMPT_V1
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import DbSessionFactory, get_db_factory
from app.ai.runtime.errors import ErrorCode, to_error_code
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, AgentTurnResult, ModelConfig
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Error,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)
from app.auth import get_current_user
from app.config import settings
from app.rate_limit import limiter
from app.repositories.conversation import ConversationRepository
from app.schemas.conversations import ChatTurnRequest

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/{conversation_id}/turns")
@limiter.limit("30/minute")
async def post_turn(
    request: Request,
    conversation_id: uuid.UUID,
    body: ChatTurnRequest,
    user_id: str = Depends(get_current_user),
    db_factory: DbSessionFactory = Depends(get_db_factory),
    anthropic_client: AsyncAnthropic = Depends(get_anthropic),
    langfuse: LangfuseClient = Depends(get_langfuse),
) -> EventSourceResponse:
    """Run one agent turn and stream the resulting events as SSE.

    Auth and slowapi are unmodified from A1.9 — both work the same on a
    streaming response as they did on the JSON one. Errors raised before
    the response starts (auth, validation, ownership) propagate to the
    global exception handlers and return a regular JSON error body.
    """
    user_uuid = uuid.UUID(user_id)

    # D6: implicit conversation creation on first turn. Run before opening
    # the SSE stream so a 404/409 surfaces as a normal HTTP error rather
    # than an SSE error frame the client has to special-case.
    async with db_factory() as db:
        await ConversationRepository.ensure_owned_conversation(
            db, conversation_id=conversation_id, user_id=user_uuid
        )

    emitter = SSEEmitter()

    # TODO(SEV-484): replace with the loop's own turn_id once B2.4 surfaces
    # it through the emitter. Today this UUID has no relation to
    # ``agent_turns.id``, so clients cannot correlate it with DB rows.
    turn_id = uuid.uuid4()

    async def _drive_turn() -> None:
        try:
            await emitter.emit(
                TurnStarted(turn_id=turn_id, conversation_id=conversation_id)
            )
            result = await run_agent_turn(
                user_id=user_uuid,
                conversation_id=conversation_id,
                user_message=body.message,
                anthropic_client=anthropic_client,
                db_factory=db_factory,
                tool_registry=EMPTY_REGISTRY,
                system_prompt=SYSTEM_PROMPT_V1,
                model_config=ModelConfig(model_id=MODELS.MAIN),
                hard_caps=HardCaps(),
                langfuse=langfuse,
                environment=settings.environment,
            )
            await _emit_result(emitter, turn_id=turn_id, result=result)
            logger.info(
                "chat_turn_completed",
                conversation_id=str(conversation_id),
                user_id=str(user_uuid),
                turn_id=str(turn_id),
                terminal_state=result.terminal_state,
                iterations_count=result.iterations_count,
            )
        except asyncio.CancelledError:
            # Client disconnect — surface no Sentry event, just stop.
            raise
        except Exception as exc:
            # ``run_agent_turn`` traps Anthropic / cap-breach failures and
            # surfaces them via ``terminal_state``; reaching this branch
            # means something outside the loop raised. The driver runs as
            # a detached task, so FastAPI's global handler never sees the
            # exception — escalate to Sentry explicitly.
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("conversation_id", str(conversation_id))
                scope.set_tag("user_id", str(user_uuid))
                scope.set_tag("turn_id", str(turn_id))
                sentry_sdk.capture_exception(exc)
            logger.exception(
                "chat_turn_driver_failed",
                conversation_id=str(conversation_id),
                user_id=str(user_uuid),
            )
            await emitter.emit(
                Error(code=to_error_code(exc), message=str(exc))
            )
        finally:
            await emitter.close()

    async def _stream() -> AsyncIterator[ServerSentEvent]:
        # Hold a strong reference to the driver task so the event loop
        # can't GC it mid-turn.
        task = asyncio.create_task(_drive_turn())
        try:
            async for event in emitter.iter_events():
                yield ServerSentEvent(
                    data=event.model_dump_json(),
                    event=event.type,
                    id=event.id,
                )
        finally:
            # On client disconnect the generator is cancelled mid-iter.
            # Cancel the driver too — otherwise it can fill the emitter
            # queue (nothing draining it) and block forever on
            # ``emitter.emit``, leaking the task and its in-flight
            # Anthropic call.
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return EventSourceResponse(_stream())


# Mirrors ``_BREACH_TO_ERROR_CODE`` in ``app.ai.runtime.loop`` — the loop
# writes these strings to ``agent_turns.terminal_state`` when a cap ends
# the turn, and we surface the matching ErrorCode on the wire so iOS can
# branch on the failure mode. ``error`` and unknown states fall through
# to ``INTERNAL_ERROR``; B2.4 will plumb the loop's real ErrorCode
# through ``AgentTurnResult`` and replace this table.
_TERMINAL_STATE_TO_ERROR_CODE: dict[str, ErrorCode] = {
    "iteration_limit": ErrorCode.TURN_ITERATION_LIMIT,
    "tool_call_limit": ErrorCode.TOOL_CALL_LIMIT,
    "output_token_limit": ErrorCode.OUTPUT_TOKEN_LIMIT,
}


async def _emit_result(
    emitter: SSEEmitter, *, turn_id: uuid.UUID, result: AgentTurnResult
) -> None:
    """Translate an :class:`AgentTurnResult` into wire events.

    For each ``text`` block in ``assistant_message_blocks`` we emit the
    full block-lifecycle (start / single delta / end) so the wire format
    matches what B2.4's streaming will produce per-token. Non-``end_turn``
    terminal states surface as an ``error`` event mapped via
    :data:`_TERMINAL_STATE_TO_ERROR_CODE`.
    """
    for index, block in enumerate(result.assistant_message_blocks):
        if block.get("type") != "text":
            continue
        block_id = f"b{index}"
        await emitter.emit(
            BlockStart(
                block={"type": "text", "block_id": block_id, "text": ""}
            )
        )
        await emitter.emit(
            TextDelta(block_id=block_id, text=block.get("text", ""))
        )
        await emitter.emit(BlockEnd(block_id=block_id))

    if result.terminal_state == "end_turn":
        await emitter.emit(
            TurnCompleted(
                turn_id=turn_id,
                terminal_state=result.terminal_state,
                total_cost_usd_micros=result.total_cost_usd_micros,
                iterations_count=result.iterations_count,
            )
        )
    else:
        code = _TERMINAL_STATE_TO_ERROR_CODE.get(
            result.terminal_state, ErrorCode.INTERNAL_ERROR
        )
        await emitter.emit(
            Error(
                code=code,
                message=f"terminal_state={result.terminal_state}",
            )
        )
