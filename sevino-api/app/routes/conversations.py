"""Chat-turn endpoint.

Per AI v0 plan A1.9 (sevino-api/docs/ai-v0-plan.md): a temporary JSON-mode
``POST /v1/conversations/{id}/turns`` that calls :func:`run_agent_turn`
and returns the assistant blocks once the turn ends. Phase 2 flips the
response to SSE without changing the URL or request shape — clients can
bind to this endpoint today.
"""

from __future__ import annotations

import uuid

import structlog
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, Request

from app.ai.anthropic_client import get_anthropic
from app.ai.models import MODELS
from app.ai.observability.langfuse import LangfuseClient, get_langfuse
from app.ai.prompts import SYSTEM_PROMPT_V1
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import DbSessionFactory, get_db_factory
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig
from app.auth import get_current_user
from app.config import settings
from app.rate_limit import limiter
from app.repositories.conversation import ConversationRepository
from app.schemas.conversations import ChatTurnRequest, ChatTurnResponse

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/{conversation_id}/turns", response_model=ChatTurnResponse)
@limiter.limit("30/minute")
async def post_turn(
    request: Request,
    conversation_id: uuid.UUID,
    body: ChatTurnRequest,
    user_id: str = Depends(get_current_user),
    db_factory: DbSessionFactory = Depends(get_db_factory),
    anthropic_client: AsyncAnthropic = Depends(get_anthropic),
    langfuse: LangfuseClient = Depends(get_langfuse),
) -> ChatTurnResponse:
    """Run one agent turn and return the assistant blocks as JSON.

    Phase 1 transport (A1.9). ``idempotency_key`` is required in the body
    but ignored until A1.10 wires the dedupe lookup against
    ``agent_turns.idempotency_key``.
    """
    user_uuid = uuid.UUID(user_id)

    # D6: implicit conversation creation on first turn. Upsert in its own
    # short transaction so the row is durable before the loop opens its
    # session-per-write factory and inserts the user_message FK.
    async with db_factory() as db:
        await ConversationRepository.ensure_owned_conversation(
            db, conversation_id=conversation_id, user_id=user_uuid
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

    return ChatTurnResponse(
        terminal_state=result.terminal_state,
        assistant_message_blocks=result.assistant_message_blocks,
    )
