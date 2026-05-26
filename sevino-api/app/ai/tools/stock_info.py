"""``get_stock_info`` — fetch live quote/profile/ratios/analyst for one ticker.

Shows a "Pulling data on X" pill; data goes to the model, not a card.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

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


_TOOL_DESCRIPTION = """Look up live US-equity stock data for a single ticker symbol. Use this when the user asks about a specific stock or company — price, valuation, fundamentals, analyst sentiment, performance vs. 52-week range, etc.

Always call this tool before stating any numeric value (price, market cap, P/E, EPS, etc.); training-data values may be stale.

Input:
  ticker — uppercase US-equity ticker (e.g. "AAPL"). One symbol per call.

Returns a JSON object with four sections:
  quote    — current price, daily change, day high/low, 52-week high/low, 50/200-day moving averages, volume, market cap, P/E, EPS, shares outstanding, earnings announcement timestamp.
  profile  — company name, sector, industry, description, CEO, website, employees, beta, IPO date, exchange, logo URL.
  ratios   — TTM fundamentals: dividend yield, payout ratio, ROE, ROA, margins (profit / operating / gross), debt/equity, current ratio, P/B, P/S, EV/EBITDA, FCF yield, PEG.
  analyst  — Wall Street targets and ratings: target high/low/median/consensus, counts of strong-buy/buy/hold/sell/strong-sell.

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

        data["performance"] = performance

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
            model_payload=data,
            ui_block=complete_pill,
            internal_trace={"raw": data},
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
