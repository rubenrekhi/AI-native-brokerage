"""Human-in-the-loop confirmation endpoint.

``POST /v1/conversations/{conversation_id}/actions/{action_id}`` is the
reverse channel for the HIL framework: the client confirms (or rejects) a
proposal the AI streamed earlier. On confirm we atomically claim the pending
action, run its executor, and stream the result back into the same
conversation as an assistant turn (see docs/ai/hil-actions.md). The client
sends only a decision — the executed parameters are the server-persisted
``payload``, never client input.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

import sentry_sdk
import structlog
from fastapi import APIRouter, Depends, Request
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse
from ulid import ULID

from app.ai.actions import (
    ACTION_EXECUTORS,
    ActionContext,
    get_action_executor,
)
from app.ai.runtime.db import DbSessionFactory, get_db_factory
from app.ai.runtime.errors import ErrorCode, to_error_code
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Error,
    TurnCompleted,
    TurnStarted,
)
from app.auth import get_current_user
from app.exceptions import ConflictError
from app.rate_limit import limiter
from app.repositories.conversation import ConversationRepository
from app.repositories.pending_action import PendingActionRepository
from app.schemas.conversations import ActionDecisionRequest

logger = structlog.get_logger(__name__)

router = APIRouter()


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "block_id": str(ULID()), "text": text}


async def _emit_block(emitter: SSEEmitter, block: dict[str, Any]) -> None:
    """Stream a fully-formed block (no deltas) — matches the tool ui_block path."""
    await emitter.emit(BlockStart(block=block))
    block_id = block.get("block_id")
    if isinstance(block_id, str):
        await emitter.emit(BlockEnd(block_id=block_id))


@router.post("/{conversation_id}/actions/{action_id}")
@limiter.limit("30/minute")
async def submit_action(
    request: Request,
    conversation_id: uuid.UUID,
    action_id: uuid.UUID,
    body: ActionDecisionRequest,
    user_id: str = Depends(get_current_user),
    db_factory: DbSessionFactory = Depends(get_db_factory),
) -> EventSourceResponse:
    user_uuid = uuid.UUID(user_id)

    # Ownership + existence (404 on either) and load the action's type while
    # the row is attached to the session.
    async with db_factory() as db:
        await ConversationRepository.ensure_owned_conversation(
            db, conversation_id=conversation_id, user_id=user_uuid
        )
        action = await PendingActionRepository.get_owned(
            db,
            action_id=action_id,
            user_id=user_uuid,
            conversation_id=conversation_id,
        )
        action_type = action.action_type

    if body.decision == "reject":
        async with db_factory() as db:
            await PendingActionRepository.reject(db, action_id=action_id)
        return _single_message_stream(
            conversation_id=conversation_id,
            db_factory=db_factory,
            blocks=[
                _text_block(
                    "Okay — I've cancelled that. Just let me know if you "
                    "change your mind."
                )
            ],
            terminal_state="rejected",
        )

    # Refuse confirm if no executor is registered — otherwise the CAS below
    # would strand the row in ``confirmed`` with no way to run or retry it.
    if action_type not in ACTION_EXECUTORS:
        raise ConflictError(
            "This action can no longer be completed.",
            code="ACTION_UNSUPPORTED",
            resource="pending_action",
        )

    # Confirm: atomic CAS. None => expired / superseded / already acted. Read
    # the payload inside the session — the row detaches once it commits.
    async with db_factory() as db:
        confirmed = await PendingActionRepository.confirm(
            db, action_id=action_id
        )
        payload = None if confirmed is None else dict(confirmed.payload)
    if payload is None:
        raise ConflictError(
            "This confirmation is no longer available — it may have expired "
            "or already been handled.",
            code="ACTION_NOT_AVAILABLE",
            resource="pending_action",
        )

    http_clients = ToolHttpClients(
        market_data=getattr(request.app.state, "market_data", None),
        alpaca=getattr(request.app.state, "alpaca", None),
        redis=getattr(request.app.state, "redis", None),
    )
    action_ctx = ActionContext(
        user_id=user_uuid, db_factory=db_factory, http_clients=http_clients
    )

    emitter = SSEEmitter()

    async def _execute_and_record() -> tuple[Any, list[dict[str, Any]]]:
        """Run the side effect and persist its outcome.

        Awaited under ``asyncio.shield``: once the action is confirmed, the
        executor and its bookkeeping run to completion even if the client
        disconnects mid-stream — the one place a dropped write would lose a
        real side effect.
        """
        try:
            executor = get_action_executor(action_type)
            result = await executor(payload, action_ctx)
        except Exception as exc:
            logger.exception(
                "action_execute_failed",
                action_id=str(action_id),
                action_type=action_type,
            )
            await _safe_mark(
                db_factory,
                action_id=action_id,
                executed=False,
                result={"error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        await _safe_mark(
            db_factory,
            action_id=action_id,
            executed=result.status == "executed",
            result=result.summary,
        )
        blocks: list[dict[str, Any]] = [_text_block(result.narration)]
        if result.result_block is not None:
            blocks.append(result.result_block.model_dump(mode="json"))
        await _safe_append_assistant(
            db_factory, conversation_id=conversation_id, blocks=blocks
        )
        logger.info(
            "action_confirmed_executed",
            action_id=str(action_id),
            action_type=action_type,
            terminal_state=result.status,
            conversation_id=str(conversation_id),
        )
        return result, blocks

    async def _drive() -> None:
        turn_id = uuid.uuid4()
        try:
            await emitter.emit(
                TurnStarted(
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    card_context_source=None,
                )
            )
            try:
                result, blocks = await asyncio.shield(_execute_and_record())
            except Exception as exc:
                await emitter.emit(
                    Error(code=to_error_code(exc), message=str(exc))
                )
                return
            for block in blocks:
                await _emit_block(emitter, block)
            await emitter.emit(
                TurnCompleted(
                    turn_id=turn_id,
                    terminal_state=result.status,
                    total_cost_usd_micros=0,
                    iterations_count=0,
                )
            )
        except asyncio.CancelledError:
            # The shielded execute+record keeps running to completion; flag the
            # cut stream so a row stuck mid-confirm is observable in Sentry.
            sentry_sdk.capture_message(
                "action_confirm_stream_cancelled_after_confirm",
                level="warning",
            )
            logger.warning(
                "action_confirm_stream_cancelled",
                action_id=str(action_id),
                action_type=action_type,
            )
            raise
        except Exception:
            logger.exception(
                "action_drive_failed", action_id=str(action_id)
            )
            await emitter.emit(
                Error(
                    code=ErrorCode.INTERNAL_ERROR,
                    message="Something went wrong completing that action.",
                )
            )
        finally:
            await emitter.close()

    async def _stream() -> AsyncIterator[ServerSentEvent]:
        task = asyncio.create_task(_drive())
        try:
            async for event in emitter.iter_events():
                yield ServerSentEvent(
                    data=event.model_dump_json(),
                    event=event.type,
                    id=event.id,
                )
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return EventSourceResponse(_stream())


def _single_message_stream(
    *,
    conversation_id: uuid.UUID,
    db_factory: DbSessionFactory,
    blocks: list[dict[str, Any]],
    terminal_state: str,
) -> EventSourceResponse:
    """Stream a fixed set of assistant blocks as one turn (e.g. reject ack)."""
    emitter = SSEEmitter()

    async def _drive() -> None:
        turn_id = uuid.uuid4()
        try:
            await emitter.emit(
                TurnStarted(
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    card_context_source=None,
                )
            )
            for block in blocks:
                await _emit_block(emitter, block)
            await _safe_append_assistant(
                db_factory, conversation_id=conversation_id, blocks=blocks
            )
            await emitter.emit(
                TurnCompleted(
                    turn_id=turn_id,
                    terminal_state=terminal_state,
                    total_cost_usd_micros=0,
                    iterations_count=0,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("action_ack_stream_failed")
            await emitter.emit(
                Error(code=ErrorCode.INTERNAL_ERROR, message=None)
            )
        finally:
            await emitter.close()

    async def _stream() -> AsyncIterator[ServerSentEvent]:
        task = asyncio.create_task(_drive())
        try:
            async for event in emitter.iter_events():
                yield ServerSentEvent(
                    data=event.model_dump_json(),
                    event=event.type,
                    id=event.id,
                )
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return EventSourceResponse(_stream())


async def _safe_mark(
    db_factory: DbSessionFactory,
    *,
    action_id: uuid.UUID,
    executed: bool,
    result: dict[str, Any],
) -> None:
    """Best-effort bookkeeping. The side effect already happened in the
    executor; a failed mark must not abort the stream."""
    try:
        async with db_factory() as db:
            if executed:
                await PendingActionRepository.mark_executed(
                    db, action_id=action_id, result=result
                )
            else:
                await PendingActionRepository.mark_failed(
                    db, action_id=action_id, result=result
                )
    except Exception:
        logger.exception(
            "pending_action_mark_failed", action_id=str(action_id)
        )


async def _safe_append_assistant(
    db_factory: DbSessionFactory,
    *,
    conversation_id: uuid.UUID,
    blocks: list[dict[str, Any]],
) -> None:
    try:
        async with db_factory() as db:
            await ConversationRepository.append_assistant_message(
                db, conversation_id=conversation_id, content_blocks=blocks
            )
    except Exception:
        logger.exception(
            "action_assistant_persist_failed",
            conversation_id=str(conversation_id),
        )


__all__ = ["router"]
