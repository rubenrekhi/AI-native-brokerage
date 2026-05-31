"""SSE event types.

Wire format per event::

    id: <ulid>
    event: <type>
    data: <json>
    <empty line>

Block payloads ride as opaque dicts so the transport layer doesn't depend
on ``app/ai/blocks``.
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
    # Frozen so the wire ``id:`` can't drift from the in-memory model.
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_event_id)


class TurnStarted(_BaseEvent):
    type: Literal["turn_started"] = "turn_started"
    turn_id: UUID
    conversation_id: UUID
    card_context_source: dict[str, str | None] | None = None


class Status(_BaseEvent):
    # Transient progress text outside the block model. StatusBlock covers
    # block-bound pills.
    type: Literal["status"] = "status"
    label: str


class BlockStart(_BaseEvent):
    type: Literal["block_start"] = "block_start"
    block: dict[str, Any]


class TextDelta(_BaseEvent):
    type: Literal["text_delta"] = "text_delta"
    block_id: str
    text: str


class BlockData(_BaseEvent):
    # Partial JSON patch; clients merge by field (last-write-wins).
    type: Literal["block_data"] = "block_data"
    block_id: str
    data: dict[str, Any]


class BlockEnd(_BaseEvent):
    type: Literal["block_end"] = "block_end"
    block_id: str


class TurnCompleted(_BaseEvent):
    type: Literal["turn_completed"] = "turn_completed"
    turn_id: UUID
    terminal_state: str
    total_cost_usd_micros: int
    iterations_count: int


class Error(_BaseEvent):
    # iOS branches on ``code``; ``message`` is human-readable only.
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str | None = None


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
    # ``id:`` and ``event:`` duplicate the JSON fields so SSE clients can
    # use ``addEventListener`` / ``Last-Event-ID`` without parsing JSON.
    payload = event.model_dump(mode="json")
    return (
        f"id: {event.id}\n"
        f"event: {payload['type']}\n"
        f"data: {json.dumps(payload, separators=(',', ':'))}\n"
        f"\n"
    )


def parse_wire_frame(frame: str) -> Event:
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
