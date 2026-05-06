"""Request/response schemas for the chat-turn endpoint.

Per AI v0 plan A1.9 (sevino-api/docs/ai-v0-plan.md): the JSON body shape is
the long-lived contract — Phase 2 flips the response transport to SSE but
the request shape and URL stay the same. ``idempotency_key`` is accepted
but ignored in Phase 1; A1.10 wires the dedupe lookup against
``agent_turns`` once the column lands.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatTurnRequest(BaseModel):
    message: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)


class ChatTurnResponse(BaseModel):
    """Phase 1 JSON shape. Mirrors :class:`AgentTurnResult` so clients can
    branch on ``terminal_state`` (``end_turn``, ``iteration_limit``,
    ``error``, etc.) without a second request."""

    terminal_state: str
    assistant_message_blocks: list[dict[str, Any]]
