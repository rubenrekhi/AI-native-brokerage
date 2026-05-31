"""Base class for persisted context-attachment blocks (SEV-615).

``ContextBlock`` is persisted in ``messages.content_blocks`` but is never a
member of the streamed ``Block`` union (``app.ai.blocks``) and never replayed
across turns — ``to_anthropic_content`` drops it from history. Each
``ContextKind`` has a subclass in this package that owns its ``render_hint``:
a short, ``kind``-only description of the open screen and what it shows — the
only thing the model sees, and only on the turn the attachment arrived.
``data`` is opaque to the backend and never sent to the model, so the hint
describes the screen's contents generically and never echoes a live value
(prices, balances, etc.) that would be stale by the next turn.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.conversations import ContextKind

_DEFAULT_HINT = (
    "The user has a data screen open in the app, and their message may be "
    "referring to something shown there."
)


class ContextBlock(BaseModel):
    type: Literal["context"] = "context"
    block_id: str
    kind: ContextKind
    data: dict[str, Any] = Field(default_factory=dict)

    def render_hint(self) -> str:
        """Short, ``kind``-only description of the open screen for this turn.

        Subclasses override per kind to describe what their screen shows;
        the base returns a generic hint so an unmapped kind degrades
        gracefully rather than leaking nothing. ``data`` is never read — it
        stays opaque to the backend and out of model input.
        """
        return _DEFAULT_HINT
