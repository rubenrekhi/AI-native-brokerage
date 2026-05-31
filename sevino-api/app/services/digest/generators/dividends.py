from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.brokerage import BrokerageService
from app.services.digest.cards import DividendPayment, DividendsCard
from app.services.digest.context import ET
from app.services.digest.generators._helpers import (
    money,
    parse_decimal,
    parse_datetime,
)
from app.services.digest.types import CardCandidate, DigestContext

logger = structlog.get_logger(__name__)


class DividendsGenerator:
    """Builds a digest card from recent positive dividend payments."""

    def __init__(self, *, lookback_days: int = 1) -> None:
        self._lookback_days = lookback_days

    async def generate(
        self,
        ctx: DigestContext,
        db: AsyncSession,
        alpaca: AlpacaBrokerService,
    ) -> list[CardCandidate]:
        now_et = ctx.market_state.as_of.astimezone(ET)
        window_start = now_et - timedelta(days=self._lookback_days)

        try:
            response = await BrokerageService.list_dividends(
                db, alpaca=alpaca, user_id=ctx.user_id
            )
        except NotFoundError:
            return []
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError):
            logger.warning(
                "digest_dividends_unavailable", user_id=str(ctx.user_id)
            )
            return []

        payments: list[DividendPayment] = []
        total = Decimal("0")
        symbols: set[str] = set()
        for dividend in response.dividends:
            paid_at = parse_datetime(dividend.created_at)
            amount = parse_decimal(dividend.net_amount)
            if paid_at is None or amount is None or amount <= 0:
                continue
            if paid_at.astimezone(ET) < window_start:
                continue
            symbol = dividend.symbol.upper()
            symbols.add(symbol)
            total += amount
            payments.append(
                DividendPayment(
                    symbol=symbol,
                    amount=money(amount),
                    paid_at=paid_at,
                )
            )

        if not payments:
            return []

        period_label = (
            "since yesterday" if self._lookback_days <= 1 else "this week"
        )
        related_symbols = sorted(symbols)
        card = DividendsCard(
            payments=payments,
            total_amount=money(total),
            period_label=period_label,
            related_symbols=related_symbols,
            card_context={
                "window_start": window_start.isoformat(),
                "total_amount": str(money(total)),
            },
        )
        return [
            CardCandidate(
                card=card,
                event_type="dividends",
                magnitude_score=float(total),
                related_symbols=related_symbols,
                dedupe_key=(
                    f"dividends:{ctx.user_id}:"
                    f"{window_start.date().isoformat()}"
                ),
            )
        ]
