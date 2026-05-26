"""``display_stock_card`` — render the inline stock card.

Pre-fetches bars for every range so iOS can swap chart data without
refetching. ``get_stock_info`` is the model's data-reasoning tool; this
one is purely for the visual.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

from app.ai.blocks import Bar, RangeBars, StockCardBlock, StockStats
from app.ai.tools._performance import (
    PERFORMANCE_RANGES,
    bars_from_chart,
    change_for_range,
)
from app.ai.tools.base import Tool, ToolContext, ToolResult
from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)

logger = structlog.get_logger(__name__)


_RANGE_OPTIONS: tuple[str, ...] = PERFORMANCE_RANGES
_DEFAULT_RANGE: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] = "1M"


_TOOL_DESCRIPTION = """Render the inline visual stock card to the user for one US-equity ticker. The card shows a logo, current price, daily change, a chart, and (with ``expanded: true``) a stats grid with valuation/technical fields.

Call this when it would be useful for the user to *see* a stock — a chart of how it has moved, or its current price + key stats — rather than only read about it. The card replaces *data dumps* in prose (lists of price/volume/P-E/52w fields), not conversational answers; keep answering the user's question in plain text and call this tool alongside to add the visual.

This tool is independent of ``get_stock_info``. They do not have to be paired — call ``get_stock_info`` to read data for your own reasoning; call ``display_stock_card`` separately when the user benefits from seeing the visual.

Use it at most once per turn per symbol. Skip it when the stock is only a passing mention, when you are reasoning about a ticker you are not recommending, or when the answer is one short sentence that doesn't need a chart.

Inputs:
  symbol — uppercase US-equity ticker (e.g. "AAPL"). One symbol per call.
  range — initial timeframe to display. Pick based on what you're answering: "1D" for intraday/today, "1W"/"1M" for short-term context, "3M"/"6M" for medium-term trends, "1Y" when discussing year-over-year performance or annual returns. Default "1M". The card pre-loads every range so the user can still slide to others; this only sets where it lands first.
  expanded — when true, include a stats grid below the chart (open/high/low, 52-week range, volume, market cap, P/E, EPS, dividend yield, etc.). Use this when the user asked about valuation, fundamentals, or technicals — not for casual "how is AMD doing" questions where the compact card is less cluttered. Default false.

Returns ``{"displayed": true, ...}`` on success (the card is now visible to the user). Returns ``{"error": "...", "symbol": "..."}`` on lookup failure; in that case no card is shown and you should briefly apologise to the user."""


class DisplayStockCardInput(BaseModel):
    symbol: str = Field(
        ...,
        description=(
            "US-equity ticker symbol (e.g. 'AAPL'). Case-insensitive; the "
            "tool normalises to uppercase. One symbol per call."
        ),
        min_length=1,
        max_length=10,
    )
    range: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] = Field(
        default=_DEFAULT_RANGE,
        description=(
            "Initial timeframe for the chart. Pick based on the timeframe "
            "of your answer: '1D' for intraday, '1W'/'1M' for short-term, "
            "'3M'/'6M' for medium-term, '1Y' for year-over-year. The card "
            "pre-loads every range; this only sets the starting view."
        ),
    )
    expanded: bool = Field(
        default=False,
        description=(
            "When true, include the valuation/technical stats grid "
            "(open/high/low, 52-week range, volume, market cap, P/E, etc.) "
            "below the chart. Use for fundamentals/valuation answers; skip "
            "for casual lookups where compact is cleaner."
        ),
    )


def _color_state(change_pct_fraction: float) -> Literal["positive", "negative", "neutral"]:
    # Takes a fraction (0.0065 = 0.65%), not raw FMP percent. ±1e-9 absorbs
    # floating-point dust on a flat day.
    if change_pct_fraction > 1e-9:
        return "positive"
    if change_pct_fraction < -1e-9:
        return "negative"
    return "neutral"


def _none_if_zero(value: Any) -> Any:
    # FMP returns missing fields as 0/"0"/"" instead of null. Drop them so
    # iOS skips the row instead of showing "$0.00". The bool narrowing
    # avoids matching False (Python equates False == 0).
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
        return None
    if isinstance(value, str) and value in ("", "0"):
        return None
    return value


def _build_stats(
    quote: dict[str, Any],
    profile: dict[str, Any],
    ratios: dict[str, Any],
) -> StockStats:
    return StockStats(
        open=_none_if_zero(quote.get("open")),
        day_high=_none_if_zero(quote.get("day_high")),
        day_low=_none_if_zero(quote.get("day_low")),
        previous_close=_none_if_zero(quote.get("previous_close")),
        year_high=_none_if_zero(quote.get("year_high")),
        year_low=_none_if_zero(quote.get("year_low")),
        volume=_none_if_zero(quote.get("volume")),
        avg_volume=_none_if_zero(quote.get("avg_volume")),
        market_cap=_none_if_zero(quote.get("market_cap")),
        pe_ratio=_none_if_zero(quote.get("pe_ratio")),
        eps=_none_if_zero(quote.get("eps")),
        beta=_none_if_zero(profile.get("beta")),
        dividend_yield=_none_if_zero(ratios.get("dividend_yield")),
        exchange=_none_if_zero(profile.get("exchange")),
    )


class DisplayStockCard(Tool[DisplayStockCardInput]):
    name: ClassVar[str] = "display_stock_card"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = DisplayStockCardInput

    async def execute(
        self, input: DisplayStockCardInput, ctx: ToolContext
    ) -> ToolResult:
        symbol = input.symbol.upper()
        initial_range = input.range
        expanded = input.expanded

        market_data = ctx.http_clients.market_data
        if market_data is None:
            logger.warning(
                "display_stock_card_market_data_unavailable", symbol=symbol
            )
            return ToolResult(
                model_payload={
                    "error": "Market data service is not configured in this environment.",
                    "symbol": symbol,
                },
            )

        # Only the initial range is load-bearing; iOS falls back to ``bars``
        # for missing ranges, so other range failures are non-fatal.
        info_task = market_data.get_stock_info(symbol)
        chart_tasks = [market_data.get_chart(symbol, r) for r in _RANGE_OPTIONS]
        results = await asyncio.gather(
            info_task, *chart_tasks, return_exceptions=True
        )
        info_result, *chart_results = results

        if isinstance(info_result, Exception):
            return self._fail_for_lookup_error(symbol, info_result)

        chart_by_range: dict[str, Any] = dict(zip(_RANGE_OPTIONS, chart_results))

        initial_chart = chart_by_range.get(initial_range)
        if isinstance(initial_chart, Exception) or initial_chart is None:
            exc = initial_chart if isinstance(initial_chart, Exception) else MarketDataError(
                f"chart fetch failed for initial range {initial_range}",
                symbol=symbol,
            )
            return self._fail_for_lookup_error(symbol, exc)

        quote = info_result["quote"]
        profile = info_result["profile"]
        ratios = info_result["ratios"]

        # FMP returns ``change_percent`` as percent ("0.65" = 0.65%); iOS
        # expects a fraction. Convert here so iOS stays FMP-agnostic.
        change_pct_fraction = float(quote.get("change_percent", "0")) / 100.0
        price = float(quote.get("price", "0"))
        daily_change_abs = float(quote.get("change", "0"))

        initial_bars = bars_from_chart(initial_chart)
        bars_by_range: list[RangeBars] = []
        for r, chart in zip(_RANGE_OPTIONS, chart_results):
            if isinstance(chart, Exception):
                logger.warning(
                    "display_stock_card_chart_range_failed",
                    symbol=symbol,
                    range=r,
                    error=str(chart),
                    exc_type=type(chart).__name__,
                )
                continue
            range_bars_list = bars_from_chart(chart)
            range_change_abs, range_change_pct = change_for_range(
                range_label=r,
                bars=range_bars_list,
                price=price,
                daily_change_abs=daily_change_abs,
                daily_change_pct=change_pct_fraction,
            )
            bars_by_range.append(
                RangeBars(
                    range=r,
                    bars=range_bars_list,
                    change_abs=range_change_abs,
                    change_pct=range_change_pct,
                )
            )

        stats = _build_stats(quote, profile, ratios) if expanded else None

        # Top-level change reflects the initial range; the slider reads
        # later values from ``bars_by_range``.
        initial_change_abs, initial_change_pct = change_for_range(
            range_label=initial_range,
            bars=initial_bars,
            price=price,
            daily_change_abs=daily_change_abs,
            daily_change_pct=change_pct_fraction,
        )

        stock_card = StockCardBlock(
            block_id=str(ULID()),
            symbol=symbol,
            company_name=profile.get("name") or symbol,
            logo_url=profile.get("logo_url"),
            price=price,
            change_abs=initial_change_abs,
            change_pct=initial_change_pct,
            color_state=_color_state(initial_change_pct),
            bars=initial_bars,
            bars_by_range=bars_by_range or None,
            range=initial_range,
            range_options=list(_RANGE_OPTIONS),
            stats=stats,
        )

        return ToolResult(
            model_payload={
                "displayed": True,
                "symbol": symbol,
                "range": initial_range,
                "expanded": expanded,
            },
            ui_block=stock_card,
            internal_trace={
                "quote": quote,
                "ranges_loaded": [rb.range for rb in bars_by_range],
            },
        )

    @staticmethod
    def _fail_for_lookup_error(
        symbol: str, exc: Exception
    ) -> ToolResult:
        if isinstance(exc, (MarketDataUnavailableError, MarketDataUpstreamError)):
            logger.warning(
                "display_stock_card_upstream_failure",
                symbol=symbol,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return ToolResult(
                model_payload={
                    "error": "Market data provider is temporarily unavailable.",
                    "symbol": symbol,
                },
            )
        logger.info(
            "display_stock_card_lookup_failed",
            symbol=symbol,
            error=str(exc),
            exc_type=type(exc).__name__,
        )
        return ToolResult(
            model_payload={
                "error": f"No data found for ticker {symbol}.",
                "symbol": symbol,
            },
        )
