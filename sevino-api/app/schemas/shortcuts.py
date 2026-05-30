"""Pydantic schemas for the `/v1/shortcuts` endpoint."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

ShortcutCategory = Literal[
    "first_time",
    "portfolio_state",
    "market_state",
    "radar_update",
    "capability",
    "quiet_state",
]

_SHORTCUT_NAMESPACE = uuid.UUID("5e9d3c1f-7a4b-4c2e-9f8a-1b2c3d4e5f60")


class Shortcut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    text: str
    category: ShortcutCategory

    @classmethod
    def create(cls, *, text: str, category: ShortcutCategory) -> "Shortcut":
        """Build a shortcut with a stable id derived from category + text.

        A deterministic id (uuid5) keeps a suggestion identity-stable across
        requests so the iOS list diffs cleanly instead of reshuffling.
        """
        return cls(
            id=uuid.uuid5(_SHORTCUT_NAMESPACE, f"{category}:{text}"),
            text=text,
            category=category,
        )


class ShortcutsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Shortcut]
