"""Request schema for the chat-turn endpoint.

Per AI v0 plan: the JSON request shape is the long-lived contract — B2.3
flipped the response to SSE but the request shape and URL stay the same.
``idempotency_key`` is accepted but ignored until B3.1 wires the dedupe
lookup against ``agent_turns.idempotency_key``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    message: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
