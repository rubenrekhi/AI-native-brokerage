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
from typing import Any

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    message: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)


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
