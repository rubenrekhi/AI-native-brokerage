"""Unit tests for the conversation request schemas.

``ChatTurnRequest.context`` is a typed ``AttachedContextRequest`` (SEV-615):
``kind`` is strict-validated at the wire (unknown kinds 422), ``data`` stays
opaque, and the 10 KB serialized-size cap applies. Daily Digest cards ride the
same ``context`` channel as ``kind="digest"`` (no separate field).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.conversations import (
    AttachedContextRequest,
    ChatTurnRequest,
    ContextKind,
)


class TestAttachedContextRequest:
    def test_parses_kind_and_opaque_data(self):
        req = AttachedContextRequest.model_validate(
            {"kind": "portfolio", "data": {"equity": "12500.50"}}
        )
        assert req.kind is ContextKind.PORTFOLIO
        assert req.data == {"equity": "12500.50"}

    def test_data_defaults_to_empty_dict(self):
        req = AttachedContextRequest.model_validate({"kind": "radar"})
        assert req.data == {}

    @pytest.mark.parametrize(
        "kind", ["portfolio", "holdings", "funding", "radar", "digest"]
    )
    def test_accepts_every_known_kind(self, kind):
        assert (
            AttachedContextRequest.model_validate({"kind": kind}).kind.value
            == kind
        )

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValidationError):
            AttachedContextRequest.model_validate({"kind": "ticker_detail"})

    def test_missing_kind_rejected(self):
        with pytest.raises(ValidationError):
            AttachedContextRequest.model_validate({"data": {"x": 1}})


class TestChatTurnRequestContext:
    def test_context_optional(self):
        req = ChatTurnRequest(message="hi", idempotency_key="k")
        assert req.context is None

    def test_context_parsed_into_typed_model(self):
        req = ChatTurnRequest.model_validate(
            {
                "message": "how am I doing?",
                "idempotency_key": "k",
                "context": {"kind": "holdings", "data": {"holdings": []}},
            }
        )
        assert isinstance(req.context, AttachedContextRequest)
        assert req.context.kind is ContextKind.HOLDINGS

    def test_unknown_kind_bubbles_up_as_validation_error(self):
        # Strict enum at the wire — garbage kinds 422 before the turn runs.
        with pytest.raises(ValidationError):
            ChatTurnRequest.model_validate(
                {
                    "message": "hi",
                    "idempotency_key": "k",
                    "context": {"kind": "garbage", "data": {}},
                }
            )

    def test_oversized_context_rejected(self):
        # The 10 KB cap guards the opaque ``data`` payload.
        oversized = {"blob": "x" * 11_000}
        with pytest.raises(ValidationError, match="byte limit"):
            ChatTurnRequest.model_validate(
                {
                    "message": "hi",
                    "idempotency_key": "k",
                    "context": {"kind": "portfolio", "data": oversized},
                }
            )

    def test_context_at_size_boundary_accepted(self):
        req = ChatTurnRequest.model_validate(
            {
                "message": "hi",
                "idempotency_key": "k",
                "context": {"kind": "portfolio", "data": {"note": "x" * 100}},
            }
        )
        assert req.context is not None

    def test_digest_rides_the_context_channel(self):
        # Daily Digest cards now flow through ``context`` as ``kind=digest``;
        # the card payload is opaque ``data`` (no separate ``digest_card``).
        req = ChatTurnRequest.model_validate(
            {
                "message": "what changed?",
                "idempotency_key": "k",
                "context": {
                    "kind": "digest",
                    "data": {"id": "d1", "kind": "big_move", "symbol": "AMD"},
                },
            }
        )
        assert req.context is not None
        assert req.context.kind is ContextKind.DIGEST
        assert req.context.data["kind"] == "big_move"
