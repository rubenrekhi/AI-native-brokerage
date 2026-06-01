"""``get_portfolio`` — read balances and holdings from the brokerage account.

Wraps ``PortfolioService`` snapshot + holdings (which already return
money/qty/pct as decimal strings) into a lean, server-aggregated payload for
the model: balances plus a holdings rollup, or the full per-position list.
Shared account setup, error payloads, and the pill lifecycle live in
``app.ai.utils.portfolio_tool_runtime``.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, Field

from app.ai.utils.portfolio_tool_runtime import (
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

logger = structlog.get_logger(__name__)

_TOP_HOLDINGS = 5
_CONCENTRATION_N = 3
_MAX_FULL_POSITIONS = 20


_TOOL_DESCRIPTION = """Read the user's current portfolio from their brokerage account: balances (equity, cash, buying power), today's change, total cost basis, overall unrealized gain/loss, and their holdings.

Use detail="overview" (the default) for "how am I doing", "how much do I have", "am I up today", or "what's my biggest position" — it returns balances, today's change, and a rollup of the largest holdings with their portfolio weight and concentration.

Use detail="positions" for the full holdings list with per-position cost basis, market value, and unrealized gain/loss. The 20 largest holdings by market value come back with full detail; any beyond that are listed by ticker only in "omitted_symbols" — pass those tickers in symbols=[...] to get their full detail. Pass symbols=["NVDA","AAPL"] for detail on specific holdings only ("how's my NVDA doing?"); requested symbols the user doesn't hold come back in "not_held".

All money, quantity, and percentage values are strings (e.g. "1204.10", "0.0117") representing exact decimals — never round them yourself or convert to a float. Percentages are fractions of 1 ("0.0117" = 1.17%). "holdings_value" is the current market value of all holdings and "total_cost_basis" is what was paid for them; the portfolio's overall return is given as "total_unrealized_pl" and "total_unrealized_pl_pct" (gain over cost) — quote these directly, do not compute the overall return yourself. The result includes "as_of" (UTC fetch time); balances and holdings are real-time.

Returns {"error": "...", "code": "ACCOUNT_NOT_ACTIVE" | "BROKERAGE_UNAVAILABLE" | "PORTFOLIO_UNAVAILABLE"} when the data can't be read — explain the situation to the user; do not retry repeatedly.

Prefer portfolio data already present in the user's attached context for this turn over calling this tool. For a security's own price or fundamentals (not the user's position in it), use get_stock_info instead."""


class PortfolioInput(BaseModel):
    detail: Literal["overview", "positions"] = Field(
        default="overview",
        description=(
            '"overview" (default) → balances, today\'s change, and a rollup '
            'of the largest holdings. "positions" → the full holdings list '
            "with per-position cost basis and unrealized P/L."
        ),
    )
    symbols: list[str] | None = Field(
        default=None,
        description=(
            'Optional ticker symbols to return detail for (e.g. ["NVDA"]). '
            "When set, returns those positions only and reports any not "
            "held; overrides detail."
        ),
    )


class GetPortfolio(Tool[PortfolioInput]):
    name: ClassVar[str] = "get_portfolio"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = PortfolioInput

    async def execute(
        self, input: PortfolioInput, ctx: ToolContext
    ) -> ToolResult:
        label = "Reading your portfolio"
        block_id = await emit_active(ctx, label)

        if ctx.http_clients.alpaca is None or ctx.http_clients.redis is None:
            logger.warning("portfolio_tool_deps_unavailable")
            return await fail(ctx, block_id, label, CONFIG_ERROR)

        try:
            async with ctx.db_factory() as db:
                acct_ctx, service = await open_service(ctx, db)
                snapshot, holdings = await asyncio.gather(
                    service.get_snapshot(acct_ctx),
                    service.get_holdings(acct_ctx),
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

        snap = snapshot.model_dump(mode="json")
        hold = holdings.model_dump(mode="json")
        payload = _build_portfolio_payload(input.detail, input.symbols, snap, hold)
        return await complete(
            ctx,
            block_id,
            label,
            payload,
            internal_trace={"snapshot": snap, "holdings": hold},
        )


def _build_portfolio_payload(
    detail: str,
    symbols: list[str] | None,
    snap: dict[str, Any],
    hold: dict[str, Any],
) -> dict[str, Any]:
    total = Decimal(hold.get("total_market_value") or "0")
    positions: list[dict[str, Any]] = hold.get("positions") or []
    total_cost = sum(
        (Decimal(p["cost_basis"] or "0") for p in positions), Decimal("0")
    )
    total_pl = sum(
        (Decimal(p["unrealized_pl"] or "0") for p in positions), Decimal("0")
    )
    payload: dict[str, Any] = {
        "as_of": now_iso(),
        "account_status": snap["account_status"],
        "equity": snap["equity"],
        "cash": snap["cash"],
        "buying_power": snap["buying_power"],
        "holdings_value": hold["total_market_value"],
        "total_cost_basis": _money(total_cost),
        "total_unrealized_pl": _money(total_pl),
        "total_unrealized_pl_pct": _pct(total_pl, total_cost),
        "day_change_abs": snap["daily_change_abs"],
        "day_change_pct": snap["daily_change_pct"],
    }

    if symbols:
        wanted = {s.upper() for s in symbols}
        held = {p["symbol"] for p in positions}
        payload["positions"] = [
            _position_entry(p, total) for p in positions if p["symbol"] in wanted
        ]
        payload["not_held"] = sorted(wanted - held)
        return payload

    if detail == "positions":
        payload["count"] = len(positions)
        shown = positions[:_MAX_FULL_POSITIONS]
        payload["positions"] = [_position_entry(p, total) for p in shown]
        if len(positions) > _MAX_FULL_POSITIONS:
            payload["truncated"] = True
            payload["omitted_symbols"] = [
                p["symbol"] for p in positions[_MAX_FULL_POSITIONS:]
            ]
            payload["more"] = (
                f"Showing the {_MAX_FULL_POSITIONS} largest of "
                f"{len(positions)} positions with full detail. The rest are "
                "listed in omitted_symbols by ticker only — request full "
                "detail on any of them with symbols=[...]."
            )
        return payload

    payload["holdings"] = _holdings_summary(positions, total)
    return payload


def _holdings_summary(
    positions: list[dict[str, Any]], total: Decimal
) -> dict[str, Any]:
    count = len(positions)
    if count == 0:
        return {
            "count": 0,
            "top": [],
            "concentration_note": (
                "No open positions; the portfolio is entirely cash."
            ),
        }
    top = [
        {
            "symbol": p["symbol"],
            "name": p["name"],
            "value": p["market_value"],
            "weight": _weight(p["market_value"], total),
            "day_change_pct": p["change_today_percent"],
        }
        for p in positions[:_TOP_HOLDINGS]
    ]
    k = min(_CONCENTRATION_N, count)
    top_sum = sum(
        (Decimal(p["market_value"] or "0") for p in positions[:k]),
        Decimal("0"),
    )
    pct = (top_sum / total * 100) if total > 0 else Decimal("0")
    note = (
        f"Top {k} of {count} position{'s' if count != 1 else ''} make up "
        f"{pct:.0f}% of holdings value."
    )
    return {"count": count, "top": top, "concentration_note": note}


def _position_entry(p: dict[str, Any], total: Decimal) -> dict[str, Any]:
    return {
        "symbol": p["symbol"],
        "name": p["name"],
        "qty": p["qty"],
        "avg_entry_price": p["avg_entry_price"],
        "current_price": p["current_price"],
        "market_value": p["market_value"],
        "cost_basis": p["cost_basis"],
        "unrealized_pl": p["unrealized_pl"],
        "unrealized_pl_pct": p["unrealized_plpc"],
        "day_change_abs": p["change_today"],
        "day_change_pct": p["change_today_percent"],
        "weight": _weight(p["market_value"], total),
    }


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _pct(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= 0:
        return "0.0000"
    return str((numerator / denominator).quantize(Decimal("0.0001")))


def _weight(market_value: str | None, total: Decimal) -> str:
    return _pct(Decimal(market_value or "0"), total)
