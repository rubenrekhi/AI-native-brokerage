from __future__ import annotations

import json
from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind


class DigestContextBlock(ContextBlock):
    kind: Literal[ContextKind.DIGEST] = ContextKind.DIGEST

    def render_hint(self) -> str:
        """Unlike the modal kinds, the digest hint folds in the card content.

        The user opened the chat *from* a specific Daily Digest card, so the
        card is the subject of the conversation; the model needs its contents
        to answer. It is a point-in-time briefing snapshot (not a live figure
        that drifts), and it reaches the model only on this turn, never
        replayed, so including it verbatim can't go stale (SEV-615).
        """
        return (
            "The user opened the chat from a Daily Digest card. Use its "
            "contents to inform your reply:\n"
            + json.dumps(self.data, separators=(",", ":"), default=str)
        )
