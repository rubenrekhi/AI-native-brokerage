"""Base class for persisted context-attachment blocks (SEV-615).

``ContextBlock`` is persisted in ``messages.content_blocks`` but is never a
member of the streamed ``Block`` union (``app.ai.blocks``) and never replayed
across turns; ``to_anthropic_content`` drops it from history. Each
``ContextKind`` has a subclass in this package that owns its ``render_hint``:
a short description of the open screen and what it shows. This is the only
thing the model sees, and only on the turn the attachment arrived. The hint is
``kind``-driven; a subclass may also project a small whitelist of non-stale,
categorical fields from ``data`` (e.g. the portfolio chart's selected time
range). It never echoes a live numeric value (prices, balances) that would be
stale by the next turn, and arbitrary ``data`` is never passed to the model.
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
        """Short description of the open screen for the current turn.

        Subclasses override per kind to describe what their screen shows, and
        may project a whitelisted, non-stale field from ``data`` (see
        ``PortfolioContextBlock``). The base reads nothing from ``data`` and
        returns a generic hint so an unmapped kind degrades gracefully rather
        than leaking nothing.
        """
        return _DEFAULT_HINT
