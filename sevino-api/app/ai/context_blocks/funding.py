from __future__ import annotations

from typing import Literal

from app.ai.context_blocks.base import ContextBlock
from app.schemas.conversations import ContextKind


class FundingContextBlock(ContextBlock):
    kind: Literal[ContextKind.FUNDING] = ContextKind.FUNDING

    def render_hint(self) -> str:
        return (
            "The user is currently viewing their cash / funding screen. This "
            "screen shows their uninvested cash balance and the interest "
            "(APY) it earns, interest earned this month and over its "
            "lifetime, buying power, pending deposits, the FDIC-insured "
            "limit, and controls to deposit, withdraw, or link a bank. Their "
            "message may be referring to their cash, yield, or a transfer "
            "shown here."
        )
