"""``display_stock_card`` — render the inline visual stock card to the user.

Paired with :mod:`app.ai.tools.stock_info`. The split is intentional:

* ``get_stock_info`` is the model's *eyes* — structured data the model
  reasons over, with a "Pulling data on X" status pill but no card.
* ``display_stock_card`` (this tool) is the model's *voice, visually* —
  it emits a fully-populated :class:`StockCardBlock` to the SSE stream.
  The model calls this when it judges the user should see the card.

The block carries everything iOS needs to render the card inline AND to
swap chart data client-side as the user slides the range selector: bars
for the *initial* range live on ``bars``, and the full multi-range
payload (every option in ``range_options``) lives on ``bars_by_range``.
No refetch round trip on slide.

The tool exposes two pieces of agency to the model:

* ``range`` — initial timeframe the card lands on. The model picks
  based on what it's actually answering (intraday → ``"1D"``, annual
  → ``"1Y"``, general lookup → ``"1M"``).
* ``expanded`` — whether to include the valuation stats grid below the
  chart. ``True`` for "fundamentals" or "compare this stock" answers,
  ``False`` for casual "how is X doing" lookups.

UX: no leading status pill. The model has already announced the lookup
via the ``get_stock_info`` pill on a prior tool call; a second pill
would just add noise. On success the card lands where the model placed
the ``tool_use`` in its generation; on failure no ``ui_block`` is
returned and the model is expected to apologise in text.

Context-window discipline: ``model_payload`` is a tiny ack
(``{"displayed": True, "symbol": ..., "range": ..., "expanded": ...}``)
— the full quote/chart payload lives in ``internal_trace`` for audit,
never re-tokenised on subsequent loop iterations.
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


# Range options exposed on the card's pill row, in display order.
# Re-exported as ``_RANGE_OPTIONS`` for tests/back-compat; the canonical
# tuple lives on ``_performance`` because ``get_stock_info`` fetches the
# same set.
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
    """Map a percent-change fraction onto the card's three-state color.

    Receives the post-conversion fractional value (0.0065 = 0.65%), not
    the raw FMP percent number. Treats anything within ``±1e-9`` of zero
    as neutral so floating-point dust doesn't flip the colour on a flat
    day.
    """
    if change_pct_fraction > 1e-9:
        return "positive"
    if change_pct_fraction < -1e-9:
        return "negative"
    return "neutral"


def _none_if_zero(value: Any) -> Any:
    """Collapse FMP's "0" / 0 / "" / None placeholder values to ``None``.

    FMP's quote projection defaults missing fields to ``0`` / ``"0"`` /
    empty rather than ``null``. Surfacing those as real values on the
    expanded card would show "$0.00" rows for missing data — better to
    drop them so iOS doesn't render a row.

    Type-aware checks: a plain ``value == 0`` would also match ``False``
    (Python equates the two), so we narrow each branch to its expected
    type. Today nothing in the FMP projection is boolean, but the strict
    form prevents a future regression if it ever returns one.
    """
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
    """Project the relevant fields from a :func:`get_stock_info` payload
    onto a :class:`StockStats` instance.

    Wire convention: send raw values (decimal strings or ints), iOS
    formats them at render time. The ``_none_if_zero`` filter drops
    fields the upstream couldn't resolve so the iOS view simply omits
    their row instead of showing a meaningless "0".
    """
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
    """Emit a populated ``StockCardBlock`` for one ticker."""

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

        # Fetch quote+profile (cached by ``get_stock_info``, almost
        # certainly already warm from the model's prior tool call) and
        # bars for every range option concurrently. ``return_exceptions``
        # so a single-range failure doesn't kill the whole card — only
        # the *initial* range is load-bearing; missing other ranges fall
        # back to the initial bars on iOS via ``bars(for:)``.
        info_task = market_data.get_stock_info(symbol)
        chart_tasks = [market_data.get_chart(symbol, r) for r in _RANGE_OPTIONS]
        results = await asyncio.gather(
            info_task, *chart_tasks, return_exceptions=True
        )
        info_result, *chart_results = results

        # The info call is required — if it fails the card has no
        # price, no company name, nothing to render.
        if isinstance(info_result, Exception):
            return self._fail_for_lookup_error(symbol, info_result)

        # Index chart results by range label so the initial-range
        # lookup and the per-range loop below both index in O(1)
        # instead of repeatedly zipping.
        chart_by_range: dict[str, Any] = dict(zip(_RANGE_OPTIONS, chart_results))

        # The initial range's chart is required — without it the card
        # opens to a range it can't display, which is worse than not
        # showing the card at all.
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

        # FMP delivers ``change_percent`` as a percent number ("0.65" =
        # 0.65%). The iOS card formats via ``Decimal.asSignedPercent``
        # which assumes a fraction (×100). Convert here so the wire
        # carries the fraction and the FE doesn't need to know about
        # FMP conventions.
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

        # Top-level change values reflect the *initial* range so the card
        # paints correctly before iOS reads `bars_by_range`. For the slider
        # to update the change on each pill tap, iOS pulls from
        # `bars_by_range[selectedRange]`.
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
        """Map an upstream exception to a model-facing error payload.

        Mirrors the error-bucketing in ``stock_info.py`` so the agent
        sees consistent shapes regardless of which tool failed.
        """
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
