"""``get_stock_info`` — internal stock-data lookup tool.

Wraps :meth:`app.services.market_data.MarketDataService.get_stock_info` so
the agent can fetch live quote + profile + ratios + analyst data for a
single US-equity ticker.

UX: emits a ``StatusBlock`` pill ("Pulling data on AAPL") in ``active``
state at call start, then patches it to ``complete`` / ``failed`` once the
fetch resolves. No user-facing GenUI block is rendered — the data only
flows back to the model.

Context-window discipline: the model_payload is the trimmed
``get_stock_info`` projection (~1–2 KB). Raw upstream data is stashed in
``internal_trace`` so it is auditable but never re-tokenised on subsequent
loop iterations.
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, Field
from ulid import ULID

from app.ai.blocks import StatusBlock
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
    """Fetch live quote + profile + ratios + analyst data for one ticker."""

    name: ClassVar[str] = "get_stock_info"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = StockInfoInput

    async def execute(
        self, input: StockInfoInput, ctx: ToolContext
    ) -> ToolResult:
        ticker = input.ticker.upper()
        block_id = str(ULID())
        label = f"Pulling data on {ticker}"

        # Announce the pill in ``active`` state. The loop's
        # ``_RecordingEmitter`` sees this BlockStart and skips re-emitting
        # one when ``ui_block`` comes back in the ToolResult.
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

        try:
            data = await market_data.get_stock_info(ticker)
        except (MarketDataError, MarketDataInvalidInputError) as exc:
            logger.info(
                "stock_info_lookup_failed",
                ticker=ticker,
                error=str(exc),
                exc_type=type(exc).__name__,
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
        except (MarketDataUnavailableError, MarketDataUpstreamError) as exc:
            logger.warning(
                "stock_info_upstream_failure",
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
        """Flip the active pill to ``failed`` state and return the error payload."""
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
