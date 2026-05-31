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
import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import AsyncIterator

import sentry_sdk
import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from ulid import ULID

from app.ai.anthropic_client import get_anthropic
from app.ai.models import get_default_model_config
from app.ai.observability.langfuse import LangfuseClient, get_langfuse
from app.ai.prompts import system_prompt_for
from app.ai.runtime.caps import HardCaps, get_hard_caps
from app.ai.runtime.db import DbSessionFactory, get_db_factory
from app.ai.runtime.errors import to_error_code
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import ModelConfig, ServerToolsConfig
from app.ai.tools import DEFAULT_REGISTRY, ToolHttpClients
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
from app.database import get_db
from app.exceptions import ConflictError, InvalidCursorError
from app.models.agent_turn import AgentTurn
from app.rate_limit import limiter
from app.repositories.conversation import (
    ConversationRepository,
    extract_text_preview,
)
from app.schemas.conversations import (
    ChatTurnRequest,
    ConversationListItem,
    ConversationListResponse,
    ConversationMessagesResponse,
    MessageItem,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# Page-size knobs for the SEV-564 list endpoints. Bounded above so a single
# request can't materialise an unbounded query result; the lower bound on
# ``limit`` keeps callers from polling a noop.
_LIST_DEFAULT_LIMIT = 20
_LIST_MAX_LIMIT = 100
_MESSAGES_DEFAULT_LIMIT = 50
_MESSAGES_MAX_LIMIT = 200


def _encode_cursor(payload: dict[str, str]) -> str:
    """Base64url-encode a JSON cursor payload (no padding stripped — clients
    round-trip the exact string)."""
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> dict[str, str]:
    """Inverse of :func:`_encode_cursor`.

    Raises ``ValueError`` if the cursor is malformed. The route translates
    that into a 422 via the validation handler so callers see a structured
    error rather than an opaque 500.
    """
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
        parsed = json.loads(decoded)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid cursor: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Invalid cursor: payload must be an object")
    return parsed


def _parse_list_cursor(
    cursor: str | None,
) -> tuple[datetime | None, uuid.UUID | None]:
    """Decode a list-endpoint cursor into ``(last_message_at, id)`` parts."""
    if cursor is None:
        return None, None
    payload = _decode_cursor(cursor)
    ts = payload.get("last_message_at")
    rid = payload.get("id")
    if not isinstance(ts, str) or not isinstance(rid, str):
        raise ValueError("Invalid cursor: missing fields")
    return datetime.fromisoformat(ts), uuid.UUID(rid)


def _parse_messages_cursor(
    cursor: str | None,
) -> tuple[datetime | None, uuid.UUID | None]:
    """Decode a messages-endpoint cursor into ``(created_at, id)`` parts."""
    if cursor is None:
        return None, None
    payload = _decode_cursor(cursor)
    ts = payload.get("created_at")
    rid = payload.get("id")
    if not isinstance(ts, str) or not isinstance(rid, str):
        raise ValueError("Invalid cursor: missing fields")
    return datetime.fromisoformat(ts), uuid.UUID(rid)


@router.get("", response_model=ConversationListResponse)
@limiter.limit("60/minute")
async def list_conversations(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(
        default=_LIST_DEFAULT_LIMIT, ge=1, le=_LIST_MAX_LIMIT
    ),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationListResponse:
    """Paginated list of the authenticated user's conversations.

    Ordered by ``last_message_at DESC`` so the sidebar shows the most
    recently active threads at the top. Conversations whose first turn
    hasn't landed yet (``last_message_at IS NULL``) are filtered out so the
    sidebar never shows a row the user has never engaged with.

    The cursor is opaque to clients — round-trip the ``next_cursor`` value
    from a previous response untouched.
    """
    user_uuid = uuid.UUID(user_id)
    try:
        cursor_ts, cursor_id = _parse_list_cursor(cursor)
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc

    rows = await ConversationRepository.list_conversations_for_user(
        db,
        user_id=user_uuid,
        limit=limit + 1,
        cursor_last_message_at=cursor_ts,
        cursor_id=cursor_id,
    )

    items: list[ConversationListItem] = []
    next_cursor: str | None = None
    for index, (conversation, last_content_blocks) in enumerate(rows):
        if index >= limit:
            # The (limit+1)-th row is the lookahead used to detect another
            # page. Don't include it in the response — instead record the
            # last *returned* row's sort key as the next cursor.
            last_returned = rows[limit - 1][0]
            next_cursor = _encode_cursor(
                {
                    "last_message_at": last_returned.last_message_at.isoformat(),
                    "id": str(last_returned.id),
                }
            )
            break
        items.append(
            ConversationListItem(
                id=conversation.id,
                title=conversation.title,
                last_message_at=conversation.last_message_at,
                last_message_preview=extract_text_preview(last_content_blocks),
            )
        )

    return ConversationListResponse(items=items, next_cursor=next_cursor)


@router.delete("/{conversation_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a conversation. Data is retained for audit."""
    user_uuid = uuid.UUID(user_id)
    await ConversationRepository.delete_conversation(
        db, conversation_id=conversation_id, user_id=user_uuid
    )


@router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
@limiter.limit("120/minute")
async def list_conversation_messages(
    request: Request,
    conversation_id: uuid.UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(
        default=_MESSAGES_DEFAULT_LIMIT, ge=1, le=_MESSAGES_MAX_LIMIT
    ),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationMessagesResponse:
    """Paginated transcript of a single conversation, oldest message first.

    Returns 404 (not 403) when the conversation belongs to another user, so
    the endpoint can't be used to probe for the existence of conversation
    ids the caller doesn't own.

    ``content_blocks`` is the persisted JSONB column verbatim — for v0 the
    loop only persists ``text`` blocks (see SEV-571 for thinking-block
    persistence), so resumed transcripts render text-only assistant replies.
    Clients should log + drop unknown block types rather than crashing the
    resume.
    """
    user_uuid = uuid.UUID(user_id)
    try:
        cursor_ts, cursor_id = _parse_messages_cursor(cursor)
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc

    messages = await ConversationRepository.list_messages_for_conversation(
        db,
        conversation_id=conversation_id,
        user_id=user_uuid,
        limit=limit + 1,
        cursor_created_at=cursor_ts,
        cursor_id=cursor_id,
    )

    items: list[MessageItem] = []
    next_cursor: str | None = None
    for index, message in enumerate(messages):
        if index >= limit:
            last_returned = messages[limit - 1]
            next_cursor = _encode_cursor(
                {
                    "created_at": last_returned.created_at.isoformat(),
                    "id": str(last_returned.id),
                }
            )
            break
        items.append(
            MessageItem(
                id=message.id,
                role=message.role,
                created_at=message.created_at,
                content_blocks=message.content_blocks,
            )
        )

    return ConversationMessagesResponse(items=items, next_cursor=next_cursor)


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
            server_tools_config = ServerToolsConfig(
                web_search_enabled=settings.anthropic_enable_web_search,
                web_fetch_enabled=settings.anthropic_enable_web_fetch,
                code_execution_enabled=settings.anthropic_enable_code_execution,
                web_search_max_uses=settings.anthropic_web_search_max_uses,
                web_fetch_max_uses=settings.anthropic_web_fetch_max_uses,
            )
            result = await run_agent_turn(
                user_id=user_uuid,
                conversation_id=conversation_id,
                user_message=body.message,
                user_context=body.context,
                digest_card=body.digest_card,
                anthropic_client=anthropic_client,
                db_factory=db_factory,
                tool_registry=DEFAULT_REGISTRY,
                http_clients=ToolHttpClients(
                    # ``getattr`` — tests that boot a bare FastAPI app
                    # without the lifespan never populate the attribute;
                    # lifespan itself stores ``None`` when FMP_API_KEY is
                    # absent. Either way the tool handles the missing
                    # service gracefully.
                    market_data=getattr(
                        request.app.state, "market_data", None
                    ),
                ),
                system_prompt=system_prompt_for(server_tools_config),
                model_config=model_config,
                hard_caps=hard_caps,
                langfuse=langfuse,
                environment=settings.environment,
                sse_emitter=emitter,
                server_tools_config=server_tools_config,
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
            #
            # Wrapped in ``asyncio.shield`` so the Redis write survives
            # parent cancellation. Without shield, sse-starlette's task-
            # group teardown on client disconnect can re-cancel the
            # parent before this await commits, leaving the slot stuck at
            # ``in_flight`` until the 2-minute TTL self-heals — observed
            # symptom: retries with the same key 409 IDEMPOTENCY_IN_FLIGHT
            # for an extended window after the original disconnect.
            try:
                if replayable and result_turn_id is not None:
                    await asyncio.shield(
                        mark_complete(
                            redis,
                            user_id=user_uuid,
                            idempotency_key=body.idempotency_key,
                            turn_id=result_turn_id,
                        )
                    )
                else:
                    await asyncio.shield(
                        mark_failed(
                            redis,
                            user_id=user_uuid,
                            idempotency_key=body.idempotency_key,
                        )
                    )
            except asyncio.CancelledError:
                # Parent was cancelled while waiting on shield — the
                # Redis write is now running in a detached child task
                # and will complete on the event loop independently.
                # Re-raise so the cancellation continues to propagate.
                raise
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
