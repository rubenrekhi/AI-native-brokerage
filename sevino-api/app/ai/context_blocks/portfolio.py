from __future__ import annotations

from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind


class PortfolioContextBlock(ContextBlock):
    kind: Literal[ContextKind.PORTFOLIO] = ContextKind.PORTFOLIO

    def render_hint(self) -> str:
        return (
            "The user is currently viewing their portfolio. This screen "
            "shows their total account value, the gain or loss over a "
            "selected time range, and an interactive value-over-time chart "
            "with range options from one day to all-time. Their message may "
            "be referring to a figure, trend, or time period shown here."
        )
