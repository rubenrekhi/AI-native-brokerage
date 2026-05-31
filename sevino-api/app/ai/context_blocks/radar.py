from __future__ import annotations

from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind


class RadarContextBlock(ContextBlock):
    kind: Literal[ContextKind.RADAR] = ContextKind.RADAR

    def render_hint(self) -> str:
        return (
            "The user is currently viewing their radar watchlist: a list of "
            "tickers Sevino is surfacing, each with a short headline, its "
            "current price and percent change, and when the item expires, "
            "any of which they can star. Their message may be referring to "
            "one of these tickers or headlines."
        )
