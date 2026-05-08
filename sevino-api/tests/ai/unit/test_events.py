"""Unit tests for ``app/ai/transport/events.py`` (AI v0 plan B1.2).

Cover the three acceptance criteria:
1. Each event serialises to the correct ``event:`` name.
2. ``id:`` is present (and ULID-shaped) on every event.
3. Round-trip serialise→parse produces an equivalent model.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest
from pydantic import ValidationError, TypeAdapter
from ulid import ULID

from app.ai.runtime.errors import ErrorCode
from app.ai.transport.events import (
    BlockData,
    BlockEnd,
    BlockStart,
    Error,
    Event,
    Status,
    TextDelta,
    TurnCompleted,
    TurnStarted,
    parse_wire_frame,
    serialize,
)

# Crockford-base32 ULIDs are 26 chars, [0-9A-HJKMNP-TV-Z].
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def _all_event_samples() -> list[tuple[str, object]]:
    """One sample of every event variant for parametric coverage."""
    turn_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    return [
        ("turn_started", TurnStarted(turn_id=turn_id, conversation_id=conv_id)),
        ("status", Status(label="thinking…")),
        (
            "block_start",
            BlockStart(block={"type": "text", "block_id": "b1", "text": ""}),
        ),
        ("text_delta", TextDelta(block_id="b1", text="hello ")),
        ("block_data", BlockData(block_id="b2", data={"price": 123.45})),
        ("block_end", BlockEnd(block_id="b1")),
        (
            "turn_completed",
            TurnCompleted(
                turn_id=turn_id,
                terminal_state="ok",
                total_cost_usd_micros=12_345,
                iterations_count=1,
            ),
        ),
        (
            "error",
            Error(code=ErrorCode.MODEL_RATE_LIMIT, message="429 from upstream"),
        ),
    ]


class TestEventIds:
    def test_id_auto_generated_as_ulid(self):
        event = Status(label="x")
        assert _ULID_RE.match(event.id), event.id

    def test_each_event_gets_a_unique_id(self):
        ids = {Status(label="x").id for _ in range(50)}
        assert len(ids) == 50

    def test_id_can_be_overridden(self):
        # Endpoints may want to assign IDs from an external sequence
        # (e.g. for resume support); the field has a default factory but
        # is not write-protected at construction time.
        custom = str(ULID())
        event = Status(id=custom, label="x")
        assert event.id == custom

    @pytest.mark.parametrize("type_name,event", _all_event_samples())
    def test_id_present_on_every_variant(self, type_name, event):
        assert _ULID_RE.match(event.id), (type_name, event.id)


class TestEventTypeDiscriminator:
    @pytest.mark.parametrize("type_name,event", _all_event_samples())
    def test_type_field_matches_variant_name(self, type_name, event):
        # Locks the wire-level event-name string per acceptance criterion 1.
        assert event.type == type_name


class TestEventModelImmutability:
    def test_events_are_frozen(self):
        # The wire `id:` is the canonical resumption pointer — mutating
        # it after a frame has been sent would silently desync clients.
        event = Status(label="x")
        with pytest.raises(ValidationError):
            event.id = "different"  # type: ignore[misc]


class TestSerialize:
    def test_frame_starts_with_id_event_data_lines_in_order(self):
        event = TextDelta(block_id="b1", text="hi")
        frame = serialize(event)
        lines = frame.split("\n")
        assert lines[0].startswith("id: ")
        assert lines[1] == "event: text_delta"
        assert lines[2].startswith("data: ")

    def test_frame_ends_with_blank_line_terminator(self):
        # Per the SSE spec, an event is terminated by an empty line
        # (`\n\n`). curl, EventSource, and our iOS line buffer all rely
        # on this terminator.
        frame = serialize(Status(label="x"))
        assert frame.endswith("\n\n")

    @pytest.mark.parametrize("type_name,event", _all_event_samples())
    def test_event_line_matches_variant(self, type_name, event):
        frame = serialize(event)
        assert f"event: {type_name}\n" in frame

    def test_id_line_matches_event_id(self):
        event = Status(label="x")
        frame = serialize(event)
        assert f"id: {event.id}\n" in frame

    def test_data_line_is_compact_json(self):
        event = TextDelta(block_id="b1", text="hi")
        frame = serialize(event)
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload == {
            "id": event.id,
            "type": "text_delta",
            "block_id": "b1",
            "text": "hi",
        }
        # Compact (no spaces between separators) — every byte in a 50/sec
        # delta stream matters.
        assert ": " not in data_line.removeprefix("data: ")
        assert ", " not in data_line

    def test_uuid_fields_serialise_as_strings(self):
        # UUIDs must hit the wire as strings; raw `UUID(...)` repr would
        # break iOS JSONDecoder.
        turn_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        frame = serialize(TurnStarted(turn_id=turn_id, conversation_id=conv_id))
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["turn_id"] == str(turn_id)
        assert payload["conversation_id"] == str(conv_id)

    def test_error_event_serialises_error_code_value(self):
        # iOS branches on the enum's wire value — make sure the *value*
        # (e.g. "model_rate_limit") goes on the wire, not the Python enum
        # repr.
        frame = serialize(Error(code=ErrorCode.MODEL_RATE_LIMIT))
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["code"] == "model_rate_limit"

    def test_error_message_is_optional(self):
        # ErrorCode is the contract; message is human-only and may be
        # absent (e.g. cap-breach errors with no upstream exception).
        frame = serialize(Error(code=ErrorCode.CANCELLED))
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["message"] is None


class TestRoundTrip:
    @pytest.mark.parametrize("type_name,event", _all_event_samples())
    def test_wire_round_trip_preserves_model(self, type_name, event):
        # Acceptance criterion 3: the wire-format round-trip is lossless.
        frame = serialize(event)
        parsed = parse_wire_frame(frame)
        assert parsed == event
        assert type(parsed) is type(event)

    @pytest.mark.parametrize("type_name,event", _all_event_samples())
    def test_json_round_trip_via_discriminated_union(self, type_name, event):
        # The data-line JSON alone is enough to recover the model — the
        # SSE protocol-layer fields (`id:`, `event:`) are derived, not
        # primary. Useful for replay / log inspection.
        adapter = TypeAdapter(Event)
        payload = event.model_dump_json()
        parsed = adapter.validate_json(payload)
        assert parsed == event
        assert type(parsed) is type(event)


class TestParseWireFrame:
    def test_rejects_frame_without_data_line(self):
        with pytest.raises(ValueError, match="missing `data:` line"):
            parse_wire_frame("id: abc\nevent: status\n\n")

    def test_rejects_id_drift_between_wire_and_payload(self):
        # If the id: line and the JSON id ever disagree, we'd rather fail
        # loudly than silently pick one — both are supposed to be the
        # same value.
        event = Status(label="x")
        json_payload = event.model_dump_json()
        bad_frame = f"id: {ULID()}\nevent: status\ndata: {json_payload}\n\n"
        with pytest.raises(ValueError, match="`id:` line"):
            parse_wire_frame(bad_frame)

    def test_rejects_event_name_drift_between_wire_and_payload(self):
        event = Status(label="x")
        json_payload = event.model_dump_json()
        bad_frame = f"id: {event.id}\nevent: text_delta\ndata: {json_payload}\n\n"
        with pytest.raises(ValueError, match="`event:` line"):
            parse_wire_frame(bad_frame)


class TestDiscriminatedUnion:
    def test_unknown_type_is_rejected(self):
        # Strict discriminator: unknown types must raise rather than silently
        # produce a bare BaseModel — protects against schema drift between
        # backend and iOS.
        adapter = TypeAdapter(Event)
        with pytest.raises(ValidationError):
            adapter.validate_python(
                {"id": str(ULID()), "type": "not_a_real_event"}
            )

    def test_missing_required_fields_for_variant_rejected(self):
        adapter = TypeAdapter(Event)
        with pytest.raises(ValidationError):
            # text_delta requires block_id + text
            adapter.validate_python({"id": str(ULID()), "type": "text_delta"})

    def test_eight_event_variants_total(self):
        # The plan locks the protocol at 8 events for v0. If this test
        # starts failing because someone added a 9th variant, the doc
        # (`docs/ai-v0-plan.md`) and iOS `enum SSEEvent` must be updated
        # to match.
        type_names = {sample[0] for sample in _all_event_samples()}
        assert len(type_names) == 8
        assert type_names == {
            "turn_started",
            "status",
            "block_start",
            "text_delta",
            "block_data",
            "block_end",
            "turn_completed",
            "error",
        }
