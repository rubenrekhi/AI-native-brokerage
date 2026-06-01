"""``get_account_activity`` — read the user's transaction history.

A unified, time-sorted feed of executed trades, deposits/withdrawals,
dividends, and interest, with per-type totals. Answers "what trades did I make
this month?", "how much did I deposit this week?", "have my dividends come in
yet?" without the user leaving the chat.

Emits a status pill ("Looking at your account activity") mirroring
``get_stock_info``'s active→complete/failed lifecycle; the data goes to the
model, not a card.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

import sentry_sdk
import structlog
from pydantic import BaseModel, Field
from ulid import ULID

from app.ai.blocks import StatusBlock
from app.ai.tools.base import Tool, ToolContext, ToolResult
from app.ai.transport.events import BlockData, BlockStart
from app.exceptions import NotFoundError
from app.services.activity import ActivityService
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerUnavailableError

logger = structlog.get_logger(__name__)

_PILL_LABEL = "Looking at your account activity"

_TOOL_DESCRIPTION = """Read the user's own account activity — their transaction history. Use this whenever the user asks what they've done in their account: trades they made, money they deposited or withdrew, dividends or interest they received. Examples: "what trades did I make this month?", "how much have I deposited this week?", "have any of my dividends come in yet?", "what happened in my account recently?".

This reads the user's *own* account. For live market data on a stock, use `get_stock_info` instead.

Trades cover both executed orders (filled / partially filled) and still-working ones (pending / new), so you can answer "what did I buy?" and "is my order still pending?" from the same call — read each row's `status`. Canceled, rejected, and expired orders are excluded unless you set `include_canceled`.

Inputs (all optional):
  activity_types — restrict to a subset of "trade", "deposit", "withdrawal", "dividend", "interest". Omit for everything. Use ["trade"] for "what did I buy/sell", ["deposit"] for "how much did I add", etc.
  after / until — inclusive ISO-8601 bounds (e.g. "2026-05-01" or "2026-05-01T00:00:00Z"). Derive these from the current date in your context: "this month" → after the 1st of this month; "this week" → after the most recent Monday; "today" → after midnight today. Omit for all-time (best for "do I have any pending orders?"). A date-only `until` covers the whole day.
  symbol — a single ticker (e.g. "AAPL") to narrow trades and dividends to that company. Ignored for transfers and interest.
  include_canceled — set true only when the user asks about orders that didn't go through ("did my order get canceled?", "was anything rejected?"). Default false.
  limit — max rows to return (default 50). Totals always reflect the full date range, even if rows are truncated.

Returns a JSON object:
  range     — the resolved {after, until} window.
  count     — number of activity rows returned.
  matched   — total rows in the window before truncation; with `truncated: true` when count < matched.
  totals    — per-type sums over the full window: deposited, withdrawn, dividends, interest (dollar strings), plus two order counts: `executed_trades` (orders that filled / partially filled — use this for "how many trades did I make") and `open_orders` (still-working orders not yet filled — use this for "how many pending orders do I have"). A pending order counts toward `open_orders`, never `executed_trades`; a canceled order counts toward neither. Don't count the trade rows yourself — use these. A key is present only when that data was fetched.
  activities — newest-first list. Common row fields: {type, date, symbol, amount, status, summary}. Trade rows add side, order_type, qty (ordered), filled_qty (executed), price (fill price, null until filled), and limit_price (limit orders only). For a working order, lean on status, qty, and limit_price; `price`/`amount` are null until it fills. `amount` is a signed dollar string (deposits/sells/dividends/interest positive, withdrawals/buys negative); use `summary` for a human-readable one-liner.
  partial   — present and true when one data source was unavailable; caveat your answer if so.
  note      — present when a filter combination matched no sources (e.g. a symbol with only non-symbol activity types like deposits); relay it instead of reporting an empty history.

May return {"error": "..."} when the user has no active brokerage account or the service is down — tell the user briefly and don't retry. Amounts are strings to preserve exact decimals; quote them as-is. After the tool returns, answer the user in plain prose, citing the specific figures."""


class AccountActivityInput(BaseModel):
    activity_types: (
        list[Literal["trade", "deposit", "withdrawal", "dividend", "interest"]]
        | None
    ) = Field(
        default=None,
        description=(
            "Subset of activity types to return. Omit for all. Options: "
            '"trade", "deposit", "withdrawal", "dividend", "interest".'
        ),
    )
    after: str | None = Field(
        default=None,
        description=(
            "Inclusive lower bound, ISO-8601 date or datetime (e.g. "
            '"2026-05-01"). Derive from the current date for relative ranges '
            'like "this month". Omit for all-time.'
        ),
    )
    until: str | None = Field(
        default=None,
        description=(
            "Inclusive upper bound, ISO-8601 date or datetime. A date-only "
            "value covers the whole day. Omit for no upper bound."
        ),
    )
    symbol: str | None = Field(
        default=None,
        description=(
            "Single US-equity ticker to filter trades and dividends (e.g. "
            "'AAPL'). Case-insensitive; normalised to uppercase. Ignored for "
            "transfers and interest."
        ),
        min_length=1,
        max_length=10,
    )
    include_canceled: bool = Field(
        default=False,
        description=(
            "Include canceled, rejected, and expired orders. Off by default — "
            "executed and still-working (pending) orders always show. Set true "
            "only when the user asks about orders that didn't go through "
            '("did my order get canceled?", "was anything rejected?").'
        ),
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum activity rows to return (default 50).",
    )


class GetAccountActivity(Tool[AccountActivityInput]):
    name: ClassVar[str] = "get_account_activity"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = AccountActivityInput

    async def execute(
        self, input: AccountActivityInput, ctx: ToolContext
    ) -> ToolResult:
        block_id = str(ULID())
        # The loop's recording emitter dedups this so it isn't re-emitted when
        # ``ui_block`` comes back in the ToolResult.
        active_pill = StatusBlock(
            block_id=block_id, label=_PILL_LABEL, state="active"
        )
        await ctx.sse_emitter.emit(
            BlockStart(block=active_pill.model_dump(mode="json"))
        )

        alpaca = ctx.http_clients.alpaca
        if alpaca is None:
            logger.warning("account_activity_alpaca_unavailable")
            return await self._settle(
                ctx,
                block_id,
                state="failed",
                payload={
                    "error": "Account activity is not available in this environment."
                },
            )

        symbol = input.symbol.upper() if input.symbol else None
        try:
            async with ctx.db_factory() as db:
                payload = await ActivityService.get_activity(
                    db,
                    alpaca=alpaca,
                    user_id=ctx.user_id,
                    types=input.activity_types,
                    after=input.after,
                    until=input.until,
                    symbol=symbol,
                    include_canceled=input.include_canceled,
                    limit=input.limit,
                )
        except NotFoundError:
            return await self._settle(
                ctx,
                block_id,
                state="failed",
                payload={
                    "error": "You don't have an active brokerage account yet, so there's no account activity to show."
                },
            )
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            logger.warning(
                "account_activity_upstream_failed",
                user_id=str(ctx.user_id),
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return await self._settle(
                ctx,
                block_id,
                state="failed",
                payload={
                    "error": "Your account activity is temporarily unavailable."
                },
            )
        except Exception as exc:
            # Escalate genuine bugs: catching here for a graceful pill means the
            # dispatch layer's logger.exception never sees them, so without this
            # they'd be lost as a warning-level breadcrumb.
            sentry_sdk.capture_exception(exc)
            logger.warning(
                "account_activity_failed",
                user_id=str(ctx.user_id),
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return await self._settle(
                ctx,
                block_id,
                state="failed",
                payload={
                    "error": "Your account activity is temporarily unavailable."
                },
            )

        return await self._settle(
            ctx, block_id, state="complete", payload=payload
        )

    @staticmethod
    async def _settle(
        ctx: ToolContext,
        block_id: str,
        *,
        state: Literal["complete", "failed"],
        payload: dict[str, Any],
    ) -> ToolResult:
        pill = StatusBlock(block_id=block_id, label=_PILL_LABEL, state=state)
        await ctx.sse_emitter.emit(
            BlockData(block_id=block_id, data=pill.model_dump(mode="json"))
        )
        return ToolResult(model_payload=payload, ui_block=pill)
