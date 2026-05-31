"""Unit tests for the conversation request schemas.

``ChatTurnRequest.context`` is a typed ``AttachedContextRequest`` (SEV-615):
``kind`` is strict-validated at the wire (unknown kinds 422), ``data`` stays
opaque, and the 10 KB serialized-size cap applies. ``digest_card`` is the
separate Daily Digest view-state field with its own required-field + size
validation.
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
        "kind", ["portfolio", "holdings", "funding", "radar"]
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


class TestChatTurnRequestDigestCard:
    def test_chat_turn_request_accepts_without_digest_card(self) -> None:
        request = ChatTurnRequest(message="hi", idempotency_key="k1")

        assert request.digest_card is None

    def test_chat_turn_request_accepts_digest_card_with_kind_and_id(
        self,
    ) -> None:
        request = ChatTurnRequest(
            message="what changed?",
            idempotency_key="k1",
            digest_card={
                "id": "digest-1",
                "kind": "big_move",
                "card_context": {"headline": "AMD moved 5%"},
            },
        )

        assert request.digest_card == {
            "id": "digest-1",
            "kind": "big_move",
            "card_context": {"headline": "AMD moved 5%"},
        }

    @pytest.mark.parametrize(
        "digest_card",
        [
            {"id": "digest-1"},
            {"kind": "big_move"},
        ],
    )
    def test_chat_turn_request_rejects_digest_card_missing_required_fields(
        self,
        digest_card: dict[str, object],
    ) -> None:
        with pytest.raises(ValidationError):
            ChatTurnRequest(
                message="what changed?",
                idempotency_key="k1",
                digest_card=digest_card,
            )

    def test_chat_turn_request_rejects_oversized_digest_card(self) -> None:
        with pytest.raises(ValidationError, match="digest_card exceeds"):
            ChatTurnRequest(
                message="what changed?",
                idempotency_key="k1",
                digest_card={
                    "id": "digest-1",
                    "kind": "big_move",
                    "card_context": {"headline": "x" * 10_000},
                },
            )
