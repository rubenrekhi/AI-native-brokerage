from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.conversations import ChatTurnRequest


def test_chat_turn_request_accepts_without_digest_card() -> None:
    request = ChatTurnRequest(message="hi", idempotency_key="k1")

    assert request.digest_card is None


def test_chat_turn_request_accepts_digest_card_with_kind_and_id() -> None:
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
    digest_card: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ChatTurnRequest(
            message="what changed?",
            idempotency_key="k1",
            digest_card=digest_card,
        )


def test_chat_turn_request_rejects_oversized_digest_card() -> None:
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
