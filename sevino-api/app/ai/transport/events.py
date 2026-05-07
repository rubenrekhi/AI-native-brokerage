"""SSE event types emitted during an agent turn.

Per AI v0 plan B1.2 (sevino-api/docs/ai-v0-plan.md): Pydantic models for
the eight wire-level events the chat-turn endpoint streams to iOS.

Wire format (one frame per event):

    id: <ulid>
    event: <type>
    data: <json>
    <empty line>

The stable ULID ``id`` ships from day one so future ``Last-Event-ID``
resumption (post-v0) is a transport change, not a protocol change.

Block payloads ride on these events as opaque ``dict`` values: the
``Block`` discriminated union owned by ``app/ai/blocks.py`` (B1.1) keeps
its schema independent of transport, and the loop is responsible for
ensuring it puts valid block dicts on the wire. Treating blocks as
opaque here avoids a hard dependency from B1.2 onto B1.1 (the plan's
dependency graph treats them as parallel work).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from ulid import ULID

from app.ai.runtime.errors import ErrorCode

__all__ = [
    "BlockData",
    "BlockEnd",
    "BlockStart",
    "Error",
    "Event",
    "Status",
    "TextDelta",
    "TurnCompleted",
    "TurnStarted",
    "parse_wire_frame",
    "serialize",
]


def _new_event_id() -> str:
    return str(ULID())


class _BaseEvent(BaseModel):
    """Shared base for the eight SSE event variants.

    ``id`` is auto-generated as a Crockford-base32 ULID. Frozen so a
    serialised event and its in-memory model stay aligned (the wire ``id:``
    line is the canonical resumption pointer; mutating it post-emit would
    silently desync clients that already received the frame).
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_event_id)


class TurnStarted(_BaseEvent):
    """First frame of every turn — carries IDs the client uses to correlate
    the stream back to ``agent_turns`` / ``conversations`` rows.
    """

    type: Literal["turn_started"] = "turn_started"
    turn_id: UUID
    conversation_id: UUID


class Status(_BaseEvent):
    """Turn-level status note that is NOT bound to a block.

    Status pills in v0 are rendered from ``StatusBlock`` blocks (carried
    on ``block_start`` / ``block_end``); this event is reserved for
    transient progress text outside the block model — kept in the
    protocol from day one so adding it later does not bump the wire
    version.
    """

    type: Literal["status"] = "status"
    label: str


class BlockStart(_BaseEvent):
    """A new content block has begun streaming.

    ``block`` carries the initial block payload as JSON per the ``Block``
    discriminated union (``app/ai/blocks.py``). The block's own
    ``block_id`` field is what subsequent ``text_delta`` / ``block_data``
    / ``block_end`` events reference.
    """

    type: Literal["block_start"] = "block_start"
    block: dict[str, Any]


class TextDelta(_BaseEvent):
    """Append text to an open ``text`` block."""

    type: Literal["text_delta"] = "text_delta"
    block_id: str
    text: str


class BlockData(_BaseEvent):
    """Partial JSON patch to an open block.

    Used for blocks that arrive incrementally — e.g. a ``StockCardBlock``
    may stream the price first and the bars later. Clients merge ``data``
    into the block by field; semantics are last-write-wins per key.
    """

    type: Literal["block_data"] = "block_data"
    block_id: str
    data: dict[str, Any]


class BlockEnd(_BaseEvent):
    """Marks an open block as finished — no further deltas for ``block_id``."""

    type: Literal["block_end"] = "block_end"
    block_id: str


class TurnCompleted(_BaseEvent):
    """Successful terminal frame — mirrors fields from ``AgentTurnResult``."""

    type: Literal["turn_completed"] = "turn_completed"
    turn_id: UUID
    terminal_state: str
    total_cost_usd_micros: int
    iterations_count: int


class Error(_BaseEvent):
    """Error terminal frame.

    ``code`` is the closed ``ErrorCode`` enum from the runtime error
    taxonomy (A1.5). iOS branches on ``code``; ``message`` is for human
    readers only and must never be load-bearing for client behaviour.
    """

    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None


# Discriminated union covering all eight variants. Use this in collaborator
# signatures (e.g. ``SSEEmitter.emit(event: Event)``) so the type system
# enforces that only valid variants flow through.
Event = Annotated[
    Union[
        TurnStarted,
        Status,
        BlockStart,
        TextDelta,
        BlockData,
        BlockEnd,
        TurnCompleted,
        Error,
    ],
    Field(discriminator="type"),
]

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def serialize(event: _BaseEvent) -> str:
    """Render an event into the SSE wire format.

    Output ends with the empty-line frame terminator (``\\n\\n``) so it
    can be written directly to a streaming response. The ``id:`` and
    ``event:`` lines duplicate the JSON ``id`` / ``type`` fields — that
    is intentional: SSE clients address those values via the protocol
    layer (``addEventListener(name)`` / ``Last-Event-ID``) without having
    to parse the JSON, while keeping them inside the JSON makes the
    payload self-describing for round-trip parsing and replay tooling.
    """
    payload = event.model_dump(mode="json")
    return (
        f"id: {event.id}\n"
        f"event: {payload['type']}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n"
        f"\n"
    )


def parse_wire_frame(frame: str) -> Event:
    """Reverse of :func:`serialize` — used by tests and (eventually) any
    server-side replay tooling. The ``data:`` JSON is the source of
    truth; ``id:`` and ``event:`` lines are validated against it.
    """
    fields: dict[str, str] = {}
    for raw_line in frame.splitlines():
        if not raw_line:
            continue
        key, _, value = raw_line.partition(": ")
        fields[key] = value

    data = fields.get("data")
    if data is None:
        raise ValueError("SSE frame missing `data:` line")

    event = _EVENT_ADAPTER.validate_json(data)

    wire_id = fields.get("id")
    if wire_id is not None and wire_id != event.id:
        raise ValueError(
            f"SSE frame `id:` line ({wire_id!r}) disagrees with JSON id ({event.id!r})"
        )
    wire_type = fields.get("event")
    if wire_type is not None and wire_type != event.type:
        raise ValueError(
            f"SSE frame `event:` line ({wire_type!r}) disagrees with JSON type ({event.type!r})"
        )
    return event
