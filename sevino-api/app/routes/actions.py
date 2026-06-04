"""Human-in-the-loop confirmation endpoint.

``POST /v1/conversations/{conversation_id}/actions/{action_id}`` is the reverse
channel for the HIL framework. The client sends only a decision; the executed
parameters are the server-persisted ``payload``, never client input.

On **confirm** we atomically claim the action, run its handler's side effect,
then drive a **full follow-up agent turn** seeded with the handler's per-type
``resume_prompt`` (a system-initiated turn — no user bubble). On **reject** we
mark it rejected and drive the same kind of turn seeded with ``reject_prompt``.
Either way the model resumes the conversation naturally and may call further
tools — so to the user the agent simply paused for the tap and continued (see
docs/ai/hil-actions.md).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

import sentry_sdk
import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Request
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app.ai.actions import ACTION_HANDLERS, ActionContext, get_action_handler
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
from app.ai.transport.events import BlockData, Error
from app.auth import get_current_user
from app.config import settings
from app.exceptions import ConflictError
from app.rate_limit import limiter
from app.repositories.conversation import ConversationRepository
from app.repositories.pending_action import PendingActionRepository
from app.schemas.conversations import ActionDecisionRequest

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/{conversation_id}/actions/{action_id}")
@limiter.limit("30/minute")
async def submit_action(
    request: Request,
    conversation_id: uuid.UUID,
    action_id: uuid.UUID,
    body: ActionDecisionRequest,
    user_id: str = Depends(get_current_user),
    db_factory: DbSessionFactory = Depends(get_db_factory),
    anthropic_client: AsyncAnthropic = Depends(get_anthropic),
    langfuse: LangfuseClient = Depends(get_langfuse),
    model_config: ModelConfig = Depends(get_default_model_config),
    hard_caps: HardCaps = Depends(get_hard_caps),
) -> EventSourceResponse:
    user_uuid = uuid.UUID(user_id)

    # Ownership + existence (404 on either) and load the action's fields while
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
        payload = dict(action.payload)
        # The card the proposal rendered — we patch its status live so the
        # client's pending card resolves the moment the side effect lands,
        # instead of waiting for a transcript reload.
        card_block_id = action.preview.get("block_id")

    # No handler → can't execute or describe the outcome. Refuse before the CAS
    # so the row isn't stranded in a terminal state with nothing to run it.
    if action_type not in ACTION_HANDLERS:
        raise ConflictError(
            "This action can no longer be completed.",
            code="ACTION_UNSUPPORTED",
            resource="pending_action",
        )
    handler = get_action_handler(action_type)
    http_clients = ToolHttpClients(
        market_data=getattr(request.app.state, "market_data", None),
        alpaca=getattr(request.app.state, "alpaca", None),
        redis=getattr(request.app.state, "redis", None),
    )

    if body.decision == "reject":
        async with db_factory() as db:
            rejected = await PendingActionRepository.reject(
                db, action_id=action_id
            )
        if rejected is None:
            raise ConflictError(
                "This confirmation is no longer available.",
                code="ACTION_NOT_AVAILABLE",
                resource="pending_action",
            )
        seed_prompt = handler.reject_prompt(payload)
        card_status = "rejected"
    else:
        # Confirm: atomic CAS. None => expired / superseded / already acted.
        async with db_factory() as db:
            confirmed = await PendingActionRepository.confirm(
                db, action_id=action_id
            )
        if confirmed is None:
            raise ConflictError(
                "This confirmation is no longer available — it may have "
                "expired or already been handled.",
                code="ACTION_NOT_AVAILABLE",
                resource="pending_action",
            )
        # The side effect runs here, before the stream opens, so a client
        # disconnect mid-stream can't abort an already-claimed money move.
        result = await handler.execute(
            payload,
            ActionContext(
                user_id=user_uuid,
                db_factory=db_factory,
                http_clients=http_clients,
            ),
        )
        await _safe_mark(
            db_factory,
            action_id=action_id,
            executed=result.status == "executed",
            result=result.summary,
        )
        seed_prompt = result.resume_prompt
        card_status = "executed" if result.status == "executed" else "failed"

    return _stream_resume_turn(
        request=request,
        user_uuid=user_uuid,
        conversation_id=conversation_id,
        action_id=action_id,
        seed_prompt=seed_prompt,
        card_block_id=card_block_id if isinstance(card_block_id, str) else None,
        card_status=card_status,
        http_clients=http_clients,
        anthropic_client=anthropic_client,
        db_factory=db_factory,
        langfuse=langfuse,
        model_config=model_config,
        hard_caps=hard_caps,
    )


def _stream_resume_turn(
    *,
    request: Request,
    user_uuid: uuid.UUID,
    conversation_id: uuid.UUID,
    action_id: uuid.UUID,
    seed_prompt: str,
    card_block_id: str | None,
    card_status: str,
    http_clients: ToolHttpClients,
    anthropic_client: AsyncAnthropic,
    db_factory: DbSessionFactory,
    langfuse: LangfuseClient,
    model_config: ModelConfig,
    hard_caps: HardCaps,
) -> EventSourceResponse:
    """Drive a full, system-initiated agent turn seeded by ``seed_prompt`` and
    stream its events. Same transport/driver shape as the chat-turn route.

    Before the turn starts we patch the originating confirmation card's status
    so the client's pending card resolves immediately; the resumed turn then
    appends fresh blocks as usual.
    """
    emitter = SSEEmitter()

    async def _drive() -> None:
        try:
            if card_block_id is not None:
                await emitter.emit(
                    BlockData(
                        block_id=card_block_id,
                        data={"status": card_status},
                    )
                )
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
                user_message=seed_prompt,
                persist_user_message=False,
                suppress_proposals=True,
                anthropic_client=anthropic_client,
                db_factory=db_factory,
                tool_registry=DEFAULT_REGISTRY,
                http_clients=http_clients,
                system_prompt=system_prompt_for(server_tools_config),
                model_config=model_config,
                hard_caps=hard_caps,
                langfuse=langfuse,
                environment=settings.environment,
                sse_emitter=emitter,
                server_tools_config=server_tools_config,
            )
            logger.info(
                "action_resume_turn_completed",
                action_id=str(action_id),
                conversation_id=str(conversation_id),
                terminal_state=result.terminal_state,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            logger.exception(
                "action_resume_turn_failed", action_id=str(action_id)
            )
            await emitter.emit(
                Error(code=to_error_code(exc), message=str(exc))
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
    handler; a failed mark must not abort the stream."""
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


__all__ = ["router"]
