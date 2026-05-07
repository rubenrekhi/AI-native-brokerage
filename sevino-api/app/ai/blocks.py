"""Discriminated-union schemas for assistant UI blocks.

Per AI v0 plan B1.1 (sevino-api/docs/ai-v0-plan.md). The agent loop streams
blocks via SSE and persists the final list to ``messages.content_blocks``
JSONB; the wire format mirrors the iOS ``enum Block`` so both ends round-trip
identically. ``StockCardBlock`` joins the union in C1.3 — adding a variant is
just a new subclass plus an entry in the union below.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    block_id: str
    text: str


class StatusBlock(BaseModel):
    type: Literal["status"] = "status"
    block_id: str
    label: str
    state: Literal["active", "complete", "failed"]


Block = Annotated[TextBlock | StatusBlock, Field(discriminator="type")]


# Module-level adapters so callers don't rebuild a TypeAdapter per validation.
# ``BlockAdapter`` validates a single block dict; ``BlockListAdapter`` validates
# the full ``messages.content_blocks`` shape.
BlockAdapter: TypeAdapter[TextBlock | StatusBlock] = TypeAdapter(Block)
BlockListAdapter: TypeAdapter[list[TextBlock | StatusBlock]] = TypeAdapter(
    list[Block]
)
