"""``radar_operations`` — read, add to, or remove from the user's radar.

One tool, three operations:

- ``get`` lists everything on the radar (ticker, company, human/ai source,
  and for AI picks the reason — ``RadarItem.context_blurb``).
- ``add`` lands a starred, user-added row (no expiry) via ``RadarService``.
- ``remove`` deletes the row regardless of source.

Emits a status pill ("Looking at your Radar" / "Adding/Removing $TICKER …")
mirroring ``get_stock_info``'s active→complete/failed lifecycle.
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
from app.exceptions import ConflictError
from app.repositories.radar_item import SOURCE_USER_ADDED
from app.schemas.radar import RadarItemRead
from app.services.radar import RadarService

logger = structlog.get_logger(__name__)


_TOOL_DESCRIPTION = """Read or change the user's radar — their personal watchlist of stocks to follow. One tool, three operations selected by `operation`:

- "get" — return everything currently on the radar. Use it whenever you need to know what's on the user's radar ("what's on my radar?", "is NVDA on my radar?") or before reasoning about their watchlist. Returns each item's ticker, company name, whether it was added by the user ("human") or surfaced by Sevino ("ai"), and for AI-surfaced items the short reason it was added. No `symbol` needed.
- "add" — put a ticker on the radar as the user's own starred pick (persists, no expiry). Requires `symbol`.
- "remove" — take a ticker off the radar, whether it was user-added or AI-surfaced. Requires `symbol`.

Call "add"/"remove" only when the user explicitly asks to change their radar ("add NVDA to my radar", "drop Apple"). Call "get" to read the radar on demand — note it may also arrive as attached context when the user has the radar open, in which case you needn't call "get" again.

Returns a JSON object echoing "operation":
  get → {"count": N, "items": [{"symbol", "company_name", "added_by": "human"|"ai", "reason" (AI picks only)}]}. An empty radar is count 0.
  add → status "added" or "already_on_radar".
  remove → status "removed" or "not_on_radar".
  Any operation may return status "error" with a human-readable "error" message. On error, tell the user briefly and don't retry the same call.

After the tool returns, answer the user in plain prose."""


class RadarOperationsInput(BaseModel):
    operation: Literal["add", "remove", "get"] = Field(
        ...,
        description=(
            '"add" to put a ticker on the radar (starred), "remove" to take '
            'one off, or "get" to list everything on the radar. "add" and '
            '"remove" require `symbol`; "get" ignores it.'
        ),
    )
    symbol: str | None = Field(
        default=None,
        description=(
            "US-equity ticker symbol (e.g. 'AAPL'). Required for 'add' and "
            "'remove'; omit for 'get'. Case-insensitive; the tool normalises "
            "to uppercase. One symbol per call."
        ),
        min_length=1,
        max_length=10,
    )


class RadarOperations(Tool[RadarOperationsInput]):
    name: ClassVar[str] = "radar_operations"
    description: ClassVar[str] = _TOOL_DESCRIPTION
    Input: ClassVar[type[BaseModel]] = RadarOperationsInput

    async def execute(
        self, input: RadarOperationsInput, ctx: ToolContext
    ) -> ToolResult:
        operation = input.operation
        symbol = input.symbol.upper() if input.symbol else None

        if operation != "get" and symbol is None:
            # add/remove need a ticker the model didn't supply; nothing
            # happened, so don't show a pill — just tell the model.
            return ToolResult(
                model_payload={
                    "operation": operation,
                    "status": "error",
                    "error": "A ticker symbol is required to add or remove a radar item.",
                }
            )

        block_id = str(ULID())
        if operation == "get":
            label = "Looking at your Radar"
        elif operation == "add":
            label = f"Adding ${symbol} to your radar"
        else:
            label = f"Removing ${symbol} from your radar"

        # The loop's recording emitter dedups this so it isn't re-emitted
        # when ``ui_block`` comes back in the ToolResult.
        active_pill = StatusBlock(
            block_id=block_id, label=label, state="active"
        )
        await ctx.sse_emitter.emit(
            BlockStart(block=active_pill.model_dump(mode="json"))
        )

        try:
            # ConflictError must escape the db_factory block so the session
            # rolls back: a duplicate add raises only after a failed flush,
            # leaving an aborted txn that can't be committed. Classified below.
            async with ctx.db_factory() as db:
                service = RadarService(ctx.http_clients.market_data, db)
                if operation == "get":
                    items = await service.list_items(ctx.user_id)
                    payload: dict[str, Any] = _build_get_payload(items)
                elif operation == "add":
                    item = await service.add_user_item(ctx.user_id, symbol)
                    payload = {
                        "operation": "add",
                        "symbol": symbol,
                        "status": "added",
                        "company_name": item.company_name,
                        "starred": item.is_favorited,
                    }
                else:
                    removed = await service.remove_user_item_by_symbol(
                        ctx.user_id, symbol
                    )
                    payload = {
                        "operation": "remove",
                        "symbol": symbol,
                        "status": "removed" if removed else "not_on_radar",
                    }
        except ConflictError as exc:
            if exc.code == "RADAR_DUPLICATE_SYMBOL":
                # Already on the radar — the end-state the user asked for
                # holds, so this is a soft success, not a failure.
                return await self._settle(
                    ctx,
                    block_id,
                    label,
                    state="complete",
                    payload={
                        "operation": "add",
                        "symbol": symbol,
                        "status": "already_on_radar",
                    },
                )
            logger.info(
                "radar_operations_rejected",
                user_id=str(ctx.user_id),
                symbol=symbol,
                code=exc.code,
            )
            return await self._settle(
                ctx,
                block_id,
                label,
                state="failed",
                payload={
                    "operation": operation,
                    "symbol": symbol,
                    "status": "error",
                    "error": exc.message,
                },
            )
        except Exception as exc:
            # Escalate genuine bugs: catching here for a graceful pill means
            # the dispatch layer's logger.exception never sees them, so without
            # this they'd be lost as a warning-level breadcrumb. ConflictError
            # (the expected business rejection) is handled above, never here.
            sentry_sdk.capture_exception(exc)
            logger.warning(
                "radar_operations_failed",
                user_id=str(ctx.user_id),
                operation=operation,
                symbol=symbol,
                error=str(exc),
                exc_type=type(exc).__name__,
            )
            return await self._settle(
                ctx,
                block_id,
                label,
                state="failed",
                payload={
                    "operation": operation,
                    "symbol": symbol,
                    "status": "error",
                    "error": "Your radar is temporarily unavailable.",
                },
            )

        return await self._settle(
            ctx, block_id, label, state="complete", payload=payload
        )

    @staticmethod
    async def _settle(
        ctx: ToolContext,
        block_id: str,
        label: str,
        *,
        state: Literal["complete", "failed"],
        payload: dict[str, Any],
    ) -> ToolResult:
        pill = StatusBlock(block_id=block_id, label=label, state=state)
        await ctx.sse_emitter.emit(
            BlockData(block_id=block_id, data=pill.model_dump(mode="json"))
        )
        return ToolResult(model_payload=payload, ui_block=pill)


def _build_get_payload(items: list[RadarItemRead]) -> dict[str, Any]:
    """Shape the radar rows for the model: ticker, company, human/ai source,
    and — for AI picks — the reason it was surfaced (``context_blurb``)."""
    entries: list[dict[str, Any]] = []
    for item in items:
        added_by = "human" if item.source == SOURCE_USER_ADDED else "ai"
        entry: dict[str, Any] = {
            "symbol": item.symbol,
            "company_name": item.company_name,
            "added_by": added_by,
        }
        if added_by == "ai":
            entry["reason"] = item.context_blurb
        entries.append(entry)
    return {"operation": "get", "count": len(entries), "items": entries}
