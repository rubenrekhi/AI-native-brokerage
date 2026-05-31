from __future__ import annotations

from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind


class HoldingsContextBlock(ContextBlock):
    kind: Literal[ContextKind.HOLDINGS] = ContextKind.HOLDINGS

    def render_hint(self) -> str:
        return (
            "The user is currently viewing their holdings: the list of "
            "positions they own, each showing its ticker, share count, "
            "market value, and unrealized gain or loss, alongside an "
            "uninvested-cash row. Tapping a position reveals its day's gain, "
            "total gain, and average cost. Their message may be referring to "
            "one of these positions or its details."
        )
