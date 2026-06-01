"""``get_stock_info`` — fetch live, tiered data for one ticker.

Shows a "Pulling data on X" pill; data goes to the model, not a card. The
``detail`` tier (or an explicit ``sections`` list) selects how much of the
assembled payload reaches the model; ``quote`` + ``performance`` always ride
along.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Literal, get_args

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

from app.ai.blocks import StatusBlock
from app.ai.tools._performance import (
    PERFORMANCE_RANGES,
    bars_from_chart,
    change_for_range,
)
from app.ai.tools.base import Tool, ToolContext, ToolResult
from app.ai.transport.events import BlockData, BlockStart
from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)

logger = structlog.get_logger(__name__)


StockSection = Literal[
    "quote",
    "profile",
    "ratios",
    "financials",
    "valuation",
    "earnings",
    "sector_context",
    "analyst",
]

_SECTION_ORDER: tuple[StockSection, ...] = get_args(StockSection)

# ``quote`` is always seeded into the payload base, so it is never gated here.
_TRIMMABLE_SECTIONS: tuple[StockSection, ...] = tuple(
    s for s in _SECTION_ORDER if s != "quote"
)

# Monotonic depth dial: each tier is a superset of the previous. ``quote`` +
# ``performance`` always ride along (see ``_build_stock_info_payload``), so the
# snapshot tier adds nothing on top of that base.
_TIERS: dict[str, frozenset[str]] = {
    "snapshot": frozenset(),
    "fundamentals": frozenset(
        {"ratios", "valuation", "financials", "earnings", "analyst"}
    ),
    "full": frozenset(_SECTION_ORDER),
}


_TOOL_DESCRIPTION = """Look up live US-equity data for a single ticker. Use this whenever the user asks about a specific stock or company — price, valuation, fundamentals, earnings, analyst sentiment, performance vs. the 52-week range, etc.

Always call this tool before stating any numeric value (price, market cap, P/E, EPS, revenue, etc.); training-data values may be stale.

Inputs:
  ticker   — uppercase US-equity ticker (e.g. "AAPL"). One symbol per call.
  detail   — how much to return (default "snapshot"):
      "snapshot"     → live quote + performance only. The default; use for price and "how's X doing / is it up today" questions.
      "fundamentals" → adds ratios, valuation, financials, earnings, and analyst ratings. Use for "is it cheap / healthy / a good buy", margins, earnings.
      "full"         → every section, plus company profile and sector/peer context. Use for deep dives, company background, and comparisons.
  sections — optional explicit list (e.g. ["earnings"]) for a surgical pull; overrides detail and returns exactly those sections. quote + performance are always included.

Re-calling at a higher tier is a full round-trip, so pick the smallest tier that answers the question up front.

Sections (quote + performance are always returned):
  quote          — price, daily change, day high/low, 52-week high/low, 50/200-day moving averages, volume, market cap, P/E, EPS, shares outstanding, next-earnings date.
  performance    — price change over 1D / 1W / 1M / 3M / 6M / 1Y (absolute + percent).
  profile        — company name, sector, industry, description, CEO, website, employees, beta, IPO date, exchange, logo URL.
  ratios         — TTM: dividend yield, payout ratio, ROE, ROA, margins (gross / operating / profit), debt/equity, current ratio, P/B, P/S, EV/EBITDA, FCF yield, PEG.
  financials     — TTM income/balance/cash-flow (revenue, net income, EBITDA, cash, total/net debt, free cash flow, capex) plus a 4-year annual trend and YoY growth.
  valuation      — P/E vs. sector and industry medians (premium/discount), plus the stock's own 5-year P/E range and P/E·P/S·P/B history.
  earnings       — forward revenue/EPS estimates, the last 4 quarters of actuals with beat/miss surprise %, and the typical post-earnings price move.
  sector_context — the sector's performance vs. the broader market, and how the stock ranks against its peers (live).
  analyst        — Wall Street price targets (high/low/median/consensus) and buy/hold/sell rating counts.

Returns {"error": "...", "ticker": "..."} on unknown ticker or upstream failure — surface a short apology to the user and ask them to confirm the ticker. Do not retry the same ticker repeatedly."""


class StockInfoInput(BaseModel):
    ticker: str = Field(
        ...,
        description=(
            "US-equity ticker symbol (e.g. 'AAPL', 'MSFT'). Case-insensitive; "
            "the tool normalises to uppercase. One symbol per call."
        ),
        min_length=1,
        max_length=10,
    )
    detail: Literal["snapshot", "fundamentals", "full"] = Field(
        default="snapshot",
        description=(
            '"snapshot" (default) → live quote + performance only; use for '
            'price and "how is X doing" questions. "fundamentals" → adds '
            "ratios, valuation, financials, earnings, and analyst ratings; "
            'use for "is it cheap / healthy / a good buy". "full" → every '
            "section, incl. company profile and sector/peer context; use for "
            "deep dives and comparisons."
        ),
    )
    sections: list[StockSection] | None = Field(
        default=None,
        description=(
            'Optional explicit sections to return (e.g. ["earnings"]). When '
            "set, returns exactly these sections and overrides detail; quote "
            "and performance are always included regardless."
        ),
    )


class GetStockInfo(Tool[StockInfoInput]):
    name: ClassVar[str] = "get_stock_info"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = StockInfoInput

    async def execute(
        self, input: StockInfoInput, ctx: ToolContext
    ) -> ToolResult:
        ticker = input.ticker.upper()
        block_id = str(ULID())
        label = f"Pulling data on {ticker}"

        # The loop's recording emitter dedups this so it isn't re-emitted
        # when ``ui_block`` comes back in the ToolResult.
        active_pill = StatusBlock(
            block_id=block_id, label=label, state="active"
        )
        await ctx.sse_emitter.emit(
            BlockStart(block=active_pill.model_dump(mode="json"))
        )

        market_data = ctx.http_clients.market_data
        if market_data is None:
            logger.warning(
                "stock_info_market_data_unavailable", ticker=ticker
            )
            return await self._fail(
                ctx=ctx,
                block_id=block_id,
                label=label,
                payload={
                    "error": "Market data service is not configured in this environment.",
                    "ticker": ticker,
                },
            )

        # Same helper + cached bars as ``display_stock_card`` so the
        # model's numbers can't drift from the card's.
        info_task = market_data.get_stock_info(ticker)
        chart_tasks = [
            market_data.get_chart(ticker, r) for r in PERFORMANCE_RANGES
        ]
        try:
            results = await asyncio.gather(
                info_task, *chart_tasks, return_exceptions=True
            )
        except Exception as exc:
            # Shouldn't happen with ``return_exceptions=True`` — degrade
            # rather than crash.
            logger.warning(
                "stock_info_gather_failed",
                ticker=ticker,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return await self._fail(
                ctx=ctx,
                block_id=block_id,
                label=label,
                payload={
                    "error": "Market data provider is temporarily unavailable.",
                    "ticker": ticker,
                },
            )

        info_result, *chart_results = results

        if isinstance(info_result, (MarketDataError, MarketDataInvalidInputError)):
            logger.info(
                "stock_info_lookup_failed",
                ticker=ticker,
                error=str(info_result),
                exc_type=type(info_result).__name__,
            )
            return await self._fail(
                ctx=ctx,
                block_id=block_id,
                label=label,
                payload={
                    "error": f"No data found for ticker {ticker}.",
                    "ticker": ticker,
                },
            )
        if isinstance(
            info_result, (MarketDataUnavailableError, MarketDataUpstreamError)
        ):
            logger.warning(
                "stock_info_upstream_failure",
                ticker=ticker,
                error=str(info_result),
                exc_type=type(info_result).__name__,
            )
            return await self._fail(
                ctx=ctx,
                block_id=block_id,
                label=label,
                payload={
                    "error": "Market data provider is temporarily unavailable.",
                    "ticker": ticker,
                },
            )
        if isinstance(info_result, BaseException):
            logger.warning(
                "stock_info_unexpected_failure",
                ticker=ticker,
                error=str(info_result),
                exc_type=type(info_result).__name__,
            )
            return await self._fail(
                ctx=ctx,
                block_id=block_id,
                label=label,
                payload={
                    "error": "Market data provider is temporarily unavailable.",
                    "ticker": ticker,
                },
            )

        data = info_result
        quote = data.get("quote", {})
        try:
            price = float(quote.get("price", "0"))
            daily_change_abs = float(quote.get("change", "0"))
            daily_change_pct = (
                float(quote.get("change_percent", "0")) / 100.0
            )
        except (TypeError, ValueError):
            price, daily_change_abs, daily_change_pct = 0.0, 0.0, 0.0

        # Skip failed ranges — the LLM falls back to daily change.
        performance: dict[str, dict[str, float]] = {}
        for r, chart in zip(PERFORMANCE_RANGES, chart_results):
            if isinstance(chart, BaseException):
                logger.warning(
                    "stock_info_chart_range_failed",
                    ticker=ticker,
                    range=r,
                    error=str(chart),
                    exc_type=type(chart).__name__,
                )
                continue
            bars = bars_from_chart(chart)
            change_abs, change_pct = change_for_range(
                range_label=r,
                bars=bars,
                price=price,
                daily_change_abs=daily_change_abs,
                daily_change_pct=daily_change_pct,
            )
            performance[r] = {
                "change_abs": change_abs,
                "change_pct": change_pct,
            }

        payload = _build_stock_info_payload(
            detail=input.detail,
            sections=input.sections,
            data=data,
            performance=performance,
        )

        complete_pill = StatusBlock(
            block_id=block_id, label=label, state="complete"
        )
        await ctx.sse_emitter.emit(
            BlockData(
                block_id=block_id,
                data=complete_pill.model_dump(mode="json"),
            )
        )
        return ToolResult(
            model_payload=payload,
            ui_block=complete_pill,
            internal_trace={"raw": {**data, "performance": performance}},
        )

    @staticmethod
    async def _fail(
        *,
        ctx: ToolContext,
        block_id: str,
        label: str,
        payload: dict[str, Any],
    ) -> ToolResult:
        failed_pill = StatusBlock(
            block_id=block_id, label=label, state="failed"
        )
        await ctx.sse_emitter.emit(
            BlockData(
                block_id=block_id,
                data=failed_pill.model_dump(mode="json"),
            )
        )
        return ToolResult(model_payload=payload, ui_block=failed_pill)


def _build_stock_info_payload(
    *,
    detail: str,
    sections: list[str] | None,
    data: dict[str, Any],
    performance: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Trim the assembled stock-info dict to the requested tier or sections.

    Builds a fresh dict so the caller's full ``data`` stays intact for the
    internal trace.
    """
    wanted = set(sections) if sections else set(_TIERS[detail])
    payload: dict[str, Any] = {
        "quote": data.get("quote", {}),
        "performance": performance,
    }
    for name in _TRIMMABLE_SECTIONS:
        if name in wanted and name in data:
            payload[name] = data[name]
    return payload
