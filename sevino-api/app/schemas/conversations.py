"""Request and response schemas for the conversation routes.

Per AI v0 plan: the JSON request shape on ``POST /turns`` is the long-lived
contract — B2.3 flipped the response to SSE but the request shape and URL
stay the same. ``idempotency_key`` is accepted but ignored until B3.1 wires
the dedupe lookup against ``agent_turns.idempotency_key``.

SEV-564 adds the list (``GET /v1/conversations``) and resume
(``GET /v1/conversations/{id}/messages``) endpoints with their response
schemas below. Both paginate via opaque cursors so the field shape can
evolve without breaking clients.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


_MAX_CONTEXT_BYTES = 10_000


class ContextKind(str, Enum):
    """Which surface the user attached context from (SEV-615).

    Strict-validated at the wire — an unknown kind 422s. The persisted
    ``ContextBlock`` and its ``render_hint`` projection live in
    ``app.ai.context_blocks``. iOS mirrors the four modal kinds in
    ``AttachedContext.swift``; ``DIGEST`` rides the same ``context`` wire
    field but has no ``AttachedContext`` chip (it carries its own digest-card
    UI + ``CardContextSource``), so it isn't in the iOS ``ContextKind`` mirror.
    """

    PORTFOLIO = "portfolio"
    HOLDINGS = "holdings"
    FUNDING = "funding"
    RADAR = "radar"
    DIGEST = "digest"


class AttachedContextRequest(BaseModel):
    """Context the client attaches when sending a message with a modal open.

    ``kind`` is strict (unknown values 422). Most of ``data`` is opaque —
    only iOS interprets each kind's full shape. The turn projects ``kind``
    (plus a whitelisted non-stale field for some kinds, e.g. the portfolio
    chart's selected range) into a short, screen-describing hint; the rest of
    ``data`` never reaches the model (see the ``ContextBlock`` subclasses in
    ``app.ai.context_blocks``).
    """

    kind: ContextKind
    data: dict[str, Any] = Field(default_factory=dict)


class ChatTurnRequest(BaseModel):
    message: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    context: AttachedContextRequest | None = Field(
        default=None,
        description="Structured context attached by the client when the user "
        "sends a message from a data surface (portfolio, holdings, funding, "
        "radar modal, or a Daily Digest card). Persisted as a ``ContextBlock`` "
        "and projected to a short model hint for the current turn only. Max "
        "serialized size: 10 KB.",
    )

    @model_validator(mode="after")
    def _validate_context_size(self) -> "ChatTurnRequest":
        if self.context is not None:
            if len(self.context.model_dump_json()) > _MAX_CONTEXT_BYTES:
                msg = f"context exceeds {_MAX_CONTEXT_BYTES} byte limit"
                raise ValueError(msg)
        return self


class ConversationListItem(BaseModel):
    """One row in the sidebar's recent-chats list."""

    id: uuid.UUID
    title: str | None
    last_message_at: datetime
    last_message_preview: str | None


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    next_cursor: str | None = None


class MessageItem(BaseModel):
    """One persisted message in a conversation transcript.

    ``content_blocks`` is the JSONB column verbatim — for v0 the loop only
    persists ``text`` blocks (see ``app/ai/runtime/loop.py``'s assistant-
    message append), so resumed transcripts render text-only assistant
    replies. Clients should treat unknown block types as a forward-compat
    signal (log + skip) rather than crashing the resume.
    """

    id: uuid.UUID
    role: str
    created_at: datetime
    content_blocks: list[dict[str, Any]]


class ConversationMessagesResponse(BaseModel):
    items: list[MessageItem]
    next_cursor: str | None = None
