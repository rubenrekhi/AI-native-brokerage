"""``get_portfolio_performance`` — read the portfolio value series over a range.

Wraps ``PortfolioService.get_history`` into gain stats, high/low, and a
downsampled trend series (at most 16 points) for the model rather than the
raw curve. Shared account setup, error payloads, and the pill lifecycle live
in ``_portfolio_common``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, Field

from app.ai.tools._portfolio_common import (
    CONFIG_ERROR,
    UPSTREAM_ERROR,
    AccountUnavailable,
    complete,
    emit_active,
    fail,
    now_iso,
    open_service,
)
from app.ai.tools.base import Tool, ToolContext, ToolResult
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.services.portfolio import PortfolioRange

logger = structlog.get_logger(__name__)

_TREND_POINTS = 16


_TOOL_DESCRIPTION = """Read how the user's portfolio value has changed over a time range. Use this for "how has my portfolio done this month", "am I up over the past year", or any return/performance question about the account as a whole (not a single stock).

Input:
  range — one of 1D, 1W, 1M, 3M, 6M, YTD, 1Y, ALL. Defaults to 1M.

Returns the starting and ending value, the absolute and percentage gain, the high and low over the range, the number of data points, and a downsampled "trend" series (at most 16 points) so you can describe the shape of the curve. All money values are strings; gain_pct is a fraction of 1 ("0.5360" = 53.60%). Includes "as_of"; history can be up to ~60s stale.

Returns {"error": "...", "code": ...} when unavailable — explain to the user and don't retry repeatedly. For a single stock's price history, use get_stock_info, not this tool."""


class PortfolioPerformanceInput(BaseModel):
    range: Literal["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] = Field(
        default="1M",
        description="Time range for the portfolio value series.",
    )


class GetPortfolioPerformance(Tool[PortfolioPerformanceInput]):
    name: ClassVar[str] = "get_portfolio_performance"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = PortfolioPerformanceInput

    async def execute(
        self, input: PortfolioPerformanceInput, ctx: ToolContext
    ) -> ToolResult:
        label = "Reading your performance"
        block_id = await emit_active(ctx, label)

        if ctx.http_clients.alpaca is None or ctx.http_clients.redis is None:
            logger.warning("portfolio_tool_deps_unavailable")
            return await fail(ctx, block_id, label, CONFIG_ERROR)

        try:
            async with ctx.db_factory() as db:
                acct_ctx, service = await open_service(ctx, db)
                history = await service.get_history(
                    acct_ctx, PortfolioRange(input.range)
                )
        except AccountUnavailable as exc:
            return await fail(ctx, block_id, label, exc.payload)
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            logger.warning(
                "portfolio_tool_alpaca_error",
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return await fail(ctx, block_id, label, UPSTREAM_ERROR)

        hist = history.model_dump(mode="json")
        payload = _build_performance_payload(hist)
        return await complete(
            ctx, block_id, label, payload, internal_trace={"history": hist}
        )


def _build_performance_payload(hist: dict[str, Any]) -> dict[str, Any]:
    points: list[dict[str, Any]] = hist.get("points") or []
    payload: dict[str, Any] = {
        "as_of": now_iso(),
        "range": hist["range"],
        "timeframe": hist["timeframe"],
        "base_value": hist["base_value"],
        "end_value": hist["end_value"],
        "gain_abs": hist["gain_abs"],
        "gain_pct": hist["gain_pct"],
        "n_points": len(points),
    }
    if points:
        hi = max(points, key=lambda pt: Decimal(pt["v"]))
        lo = min(points, key=lambda pt: Decimal(pt["v"]))
        payload["high"] = {"t": hi["t"], "v": hi["v"]}
        payload["low"] = {"t": lo["t"], "v": lo["v"]}
        payload["trend"] = _downsample(points, _TREND_POINTS)
    else:
        payload["trend"] = []
    return payload


def _downsample(
    points: list[dict[str, Any]], target: int
) -> list[dict[str, Any]]:
    if len(points) <= target:
        return list(points)
    last = len(points) - 1
    step = last / (target - 1)
    indices = sorted({round(i * step) for i in range(target)})
    return [points[i] for i in indices]
