"""Pydantic schemas for the `/v1/digest` endpoints.

iOS hand-mirrors `DigestSnapshotRead` and `DigestTodayResponse` (see
CLAUDE.md "AI wire format"); the `cards` array carries the `DigestCard`
discriminated union from `app/services/digest/cards.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.services.digest.cards import DigestCard

if TYPE_CHECKING:
    from app.models.digest import DigestSnapshot


class DigestSnapshotRead(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    ny_local_date: date
    cards: list[DigestCard]
    generated_at: datetime
    dismissed_at: datetime | None
    created_at: datetime


class DigestTodayResponse(BaseModel):
    """Response for `GET /v1/digest/today` when a snapshot exists.

    `peek_visible` tells iOS which presentation to use: ``false`` for a
    fresh (undismissed) digest that auto-opens as a full-screen cover,
    ``true`` once dismissed so Home shows the peek card instead (§20.9).
    No snapshot at all is a 204, not this body with a null snapshot.
    """

    model_config = ConfigDict(frozen=True)

    snapshot: DigestSnapshotRead
    peek_visible: bool

    @classmethod
    def from_snapshot(cls, snapshot: DigestSnapshot) -> DigestTodayResponse:
        return cls(
            snapshot=DigestSnapshotRead.model_validate(snapshot),
            peek_visible=snapshot.dismissed_at is not None,
        )
