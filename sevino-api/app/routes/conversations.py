"""Chat-turn endpoint.

Per AI v0 plan B2.3 / B2.4 / B3.2 (sevino-api/docs/ai-v0-plan.md): ``POST
/v1/conversations/{id}/turns`` returns ``text/event-stream``. The endpoint
creates an :class:`SSEEmitter`, spawns a task that runs the agent loop with
that emitter, and yields events from the emitter to the
``EventSourceResponse``. URL and request body are unchanged from the
A1.9 JSON shape — only the response transport flips.

After B2.4 the loop owns the wire envelope: it emits ``turn_started``,
per-block ``block_start`` / ``text_delta`` / ``block_end``, and the
terminal ``turn_completed`` / ``error`` frame. The driver's only
emission responsibility is to surface unexpected exceptions that escape
the loop's own error trapping (e.g. a misconfigured-caps ``ValueError``
or any defect in the loop's try/finally), since the detached driver
task is not visible to FastAPI's global exception handler.

After B3.2, every request claims an idempotency slot in Redis before the
SSE stream opens. Three outcomes:

* ``claimed``  — first-mover. Run the loop normally; on success
                 (``terminal_state == "end_turn"`` with a persisted
                 assistant message) mark the slot ``complete`` so a
                 retry replays. On any other terminal state, ``DEL`` the
                 slot so a retry can run fresh.
* ``in_flight`` — a parallel request is still running the same key. The
                 endpoint raises :class:`ConflictError` (HTTP 409) before
                 the SSE stream opens, so iOS sees a normal JSON error.
* ``complete``  — replay the persisted assistant message as a single
                 SSE stream (``turn_started`` → blocks → ``turn_completed``)
                 without invoking Anthropic. Replay completes locally in
                 milliseconds.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator

import sentry_sdk
import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from ulid import ULID

from app.ai.anthropic_client import get_anthropic
from app.ai.models import get_default_model_config
from app.ai.observability.langfuse import LangfuseClient, get_langfuse
from app.ai.prompts import SYSTEM_PROMPT_V1
from app.ai.runtime.caps import HardCaps, get_hard_caps
from app.ai.runtime.db import DbSessionFactory, get_db_factory
from app.ai.runtime.errors import to_error_code
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
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
from app.ai.transport.idempotency import (
    claim_idempotency,
    get_idempotency_redis,
    mark_complete,
    mark_failed,
)
from app.auth import get_current_user
from app.config import settings
from app.exceptions import ConflictError
from app.models.agent_turn import AgentTurn
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
    model_config: ModelConfig = Depends(get_default_model_config),
    hard_caps: HardCaps = Depends(get_hard_caps),
    redis: Redis = Depends(get_idempotency_redis),
) -> EventSourceResponse:
    """Run one agent turn and stream the resulting events as SSE.

    Auth and slowapi are unmodified from A1.9 — both work the same on a
    streaming response as they did on the JSON one. Errors raised before
    the response starts (auth, validation, ownership, idempotency 409)
    propagate to the global exception handlers and return a regular JSON
    error body.
    """
    user_uuid = uuid.UUID(user_id)

    # D6: implicit conversation creation on first turn. Run before opening
    # the SSE stream so a 404/409 surfaces as a normal HTTP error rather
    # than an SSE error frame the client has to special-case.
    async with db_factory() as db:
        await ConversationRepository.ensure_owned_conversation(
            db, conversation_id=conversation_id, user_id=user_uuid
        )

    # B3.1/B3.2: idempotency claim. The placeholder turn_id we pass in is
    # only the in_flight ownership tag — the actual ``agent_turns.id`` is
    # generated inside the loop and overwrites this value when the route
    # marks the slot ``complete``. Doing the claim here (before opening
    # the SSE stream) means a 409 surfaces as a normal HTTP error, not as
    # an SSE error frame the client has to special-case.
    placeholder_turn_id = uuid.uuid4()
    claim = await claim_idempotency(
        redis,
        user_id=user_uuid,
        idempotency_key=body.idempotency_key,
        turn_id=placeholder_turn_id,
    )

    if claim.status == "in_flight":
        raise ConflictError(
            "Idempotency key in flight",
            code="IDEMPOTENCY_IN_FLIGHT",
            detail=(
                {"turn_id": str(claim.turn_id)} if claim.turn_id else None
            ),
        )

    if claim.status == "complete":
        return await _replay_turn(
            db_factory=db_factory,
            conversation_id=conversation_id,
            user_id=user_uuid,
            turn_id=claim.turn_id,
        )

    # claim.status == "claimed" — fresh run. From here, the slot is owned
    # by this request; the driver below must call mark_complete/mark_failed
    # in its finally block so the slot transitions out of in_flight.
    emitter = SSEEmitter()

    async def _drive_turn() -> None:
        result_turn_id: uuid.UUID | None = None
        replayable = False
        try:
            # B3.3: ``disconnect_check`` deliberately not wired to
            # ``request.is_disconnected`` — this codebase's middleware
            # chain (``APIKeyMiddleware``, ``RequestLoggingMiddleware``,
            # ``CorrelationIDMiddleware``, ``SlowAPIMiddleware``) extends
            # ``BaseHTTPMiddleware``, which consumes the ASGI receive
            # channel upstream of the route. The route's
            # ``request.is_disconnected`` therefore never observes the
            # ``http.disconnect`` message and would always return False
            # in production. Cancellation is instead driven by the
            # framework's external ``task.cancel()`` when the SSE
            # asyncgen is closed by ``EventSourceResponse`` (which uses
            # raw ASGI receive in its own task group); the resulting
            # CancelledError is caught by the outer ``except`` in
            # ``run_agent_turn`` and persisted as
            # ``terminal_state='cancelled'``. The poll hook is kept on
            # the loop signature for unit-test ergonomics and so future
            # work can wire it to a working signal (e.g.
            # ``EventSourceResponse``'s ``client_close_handler_callable``).
            result = await run_agent_turn(
                user_id=user_uuid,
                conversation_id=conversation_id,
                user_message=body.message,
                anthropic_client=anthropic_client,
                db_factory=db_factory,
                tool_registry=EMPTY_REGISTRY,
                system_prompt=SYSTEM_PROMPT_V1,
                model_config=model_config,
                hard_caps=hard_caps,
                langfuse=langfuse,
                environment=settings.environment,
                sse_emitter=emitter,
            )
            result_turn_id = result.turn_id
            # Only ``end_turn`` with persisted blocks is replayable. Cap
            # breaches and Anthropic errors release the slot so a retry
            # with the same key runs fresh.
            replayable = (
                result.terminal_state == "end_turn"
                and bool(result.assistant_message_blocks)
            )
            logger.info(
                "chat_turn_completed",
                conversation_id=str(conversation_id),
                user_id=str(user_uuid),
                terminal_state=result.terminal_state,
                iterations_count=result.iterations_count,
            )
        except asyncio.CancelledError:
            # Client disconnect — surface no Sentry event, just stop.
            raise
        except Exception as exc:
            # ``run_agent_turn`` traps Anthropic / cap-breach failures and
            # emits the matching ``error`` frame itself; reaching this branch
            # means something outside the loop's normal exit paths raised
            # (e.g. a ``ValueError`` from misconfigured caps, or a defect
            # that escapes the loop's try/finally). The driver runs as a
            # detached task, so FastAPI's global handler never sees the
            # exception — escalate to Sentry explicitly and surface a
            # wire-level Error so the client doesn't hang.
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("conversation_id", str(conversation_id))
                scope.set_tag("user_id", str(user_uuid))
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
            # Idempotency slot transition. Done before closing the emitter
            # so a retry that races against close still observes the
            # complete record (and therefore replays) rather than a
            # half-cleared in_flight slot.
            try:
                if replayable and result_turn_id is not None:
                    await mark_complete(
                        redis,
                        user_id=user_uuid,
                        idempotency_key=body.idempotency_key,
                        turn_id=result_turn_id,
                    )
                else:
                    await mark_failed(
                        redis,
                        user_id=user_uuid,
                        idempotency_key=body.idempotency_key,
                    )
            except Exception:
                # Never let a Redis hiccup mask the original turn outcome —
                # the assistant message is already persisted in Postgres,
                # so the worst case is the slot self-heals after the TTL.
                logger.exception(
                    "chat_turn_idempotency_finalize_failed",
                    conversation_id=str(conversation_id),
                    user_id=str(user_uuid),
                )
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


async def _replay_turn(
    *,
    db_factory: DbSessionFactory,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    turn_id: uuid.UUID | None,
) -> EventSourceResponse:
    """Re-emit a previously persisted turn as an SSE stream (B3.2).

    The frame sequence mirrors the original turn (``turn_started`` → per-
    block ``block_start`` / ``text_delta`` / ``block_end`` → ``turn_completed``)
    so the iOS client takes the same code path on replay as on the live
    turn — modulo the ``id:`` field, which is per-stream and
    regenerated. Each persisted text block collapses to a single
    ``text_delta`` carrying the full block text; the original may have
    streamed N chunks, but the persisted JSONB stores the concatenation,
    and the client's last-write-wins merge produces the same final state
    either way.
    """
    if turn_id is None:
        # Defensive: the idempotency record was tagged ``complete`` but
        # without a parsable turn_id. Treat as an internal inconsistency —
        # the slot self-heals after the complete TTL; for this request,
        # surface a 500 via the global handler.
        logger.error(
            "chat_turn_replay_missing_turn_id",
            conversation_id=str(conversation_id),
            user_id=str(user_id),
        )
        raise RuntimeError("idempotency record missing turn_id for replay")

    async with db_factory() as db:
        loaded = await ConversationRepository.load_assistant_message_for_turn(
            db, agent_turn_id=turn_id, conversation_id=conversation_id
        )
    if loaded is None:
        # Two possible causes:
        #   1. The user reused the same idempotency_key against a
        #      different conversation (slots are scoped to user, not
        #      conversation). User error → 409 with a clear code.
        #   2. The slot was marked ``complete`` but the turn or
        #      assistant_message row is missing. Genuine data
        #      inconsistency → 500 via the global handler.
        # One extra DB lookup in the rare error path lets us return the
        # correct error code in case 1.
        async with db_factory() as db:
            existing_turn = await db.get(AgentTurn, turn_id)
        if (
            existing_turn is not None
            and existing_turn.conversation_id != conversation_id
        ):
            logger.warning(
                "chat_turn_replay_conversation_mismatch",
                conversation_id=str(conversation_id),
                user_id=str(user_id),
                turn_id=str(turn_id),
                owning_conversation_id=str(existing_turn.conversation_id),
            )
            raise ConflictError(
                "Idempotency key already used for a different conversation",
                code="IDEMPOTENCY_CONVERSATION_MISMATCH",
            )
        logger.error(
            "chat_turn_replay_message_missing",
            conversation_id=str(conversation_id),
            user_id=str(user_id),
            turn_id=str(turn_id),
        )
        raise RuntimeError("idempotency complete but assistant message missing")
    turn, message = loaded

    events: list[Event] = [
        TurnStarted(turn_id=turn.id, conversation_id=turn.conversation_id),
    ]
    for block in message.content_blocks:
        if block.get("type") != "text":
            # v0 only persists text blocks (loop.py:520). Future block
            # variants (StatusBlock, StockCardBlock) will need their own
            # replay shape; skip unknown types defensively rather than
            # emitting a malformed frame.
            continue
        block_id = block.get("block_id")
        if not isinstance(block_id, str):
            # Block was persisted before B2.4 added ``block_id`` (legacy
            # row) or the JSONB schema is corrupt. Mint a fresh ULID so
            # the wire envelope stays valid; correlation back to any
            # original streamed events is already lost. Logged so the
            # legacy-row count is visible in observability.
            logger.warning(
                "chat_turn_replay_block_id_fallback",
                conversation_id=str(conversation_id),
                user_id=str(user_id),
                turn_id=str(turn.id),
                persisted_block_id=block_id,
            )
            block_id = str(ULID())
        text = block.get("text", "")
        events.append(
            BlockStart(
                block={"type": "text", "block_id": block_id, "text": ""}
            )
        )
        events.append(TextDelta(block_id=block_id, text=text))
        events.append(BlockEnd(block_id=block_id))

    events.append(
        TurnCompleted(
            turn_id=turn.id,
            terminal_state=turn.terminal_state or "end_turn",
            total_cost_usd_micros=turn.total_cost_usd_micros,
            iterations_count=turn.iterations_count,
        )
    )

    logger.info(
        "chat_turn_replayed",
        conversation_id=str(conversation_id),
        user_id=str(user_id),
        turn_id=str(turn.id),
        block_count=len(message.content_blocks),
    )

    async def _stream() -> AsyncIterator[ServerSentEvent]:
        for event in events:
            yield ServerSentEvent(
                data=event.model_dump_json(),
                event=event.type,
                id=event.id,
            )

    return EventSourceResponse(_stream())
