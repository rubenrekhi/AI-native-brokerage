"""Daily sync of the tradeable asset universe from Alpaca.

Alpaca is the source of truth for which symbols our users can trade. We
pull the full active US-equity list once per day, construct an FMP logo
URL from each symbol, and upsert into the local ``assets`` table that
powers the ticker search typeahead.
"""

from typing import Any

import sentry_sdk
import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.asset import Asset
from app.repositories.asset import AssetRepository
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)

FMP_LOGO_URL_TEMPLATE = "https://financialmodelingprep.com/image-stock/{symbol}.png"


def _to_asset_row(alpaca_asset: dict[str, Any]) -> dict[str, Any] | None:
    # Returns None for malformed rows (missing symbol/name) so one bad
    # entry in a ~12k batch doesn't abort the whole sync.
    symbol = alpaca_asset.get("symbol")
    name = alpaca_asset.get("name")
    if not symbol or not name:
        return None
    symbol = symbol.upper()
    return {
        "symbol": symbol,
        "name": name,
        "exchange": alpaca_asset.get("exchange"),
        "tradeable": True,
        "logo_url": FMP_LOGO_URL_TEMPLATE.format(symbol=symbol),
        "alpaca_asset_id": alpaca_asset.get("id"),
    }


def _capture_with_scope(exc: Exception, *, failure_stage: str) -> None:
    # Every capture in a long-running worker process must set searchable
    # tags (see be-auditor §11.3). Structlog contextvars don't mirror onto
    # the Sentry scope, so we wire them explicitly.
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("arq_task", "sync_assets")
        scope.set_tag("failure_stage", failure_stage)
        scope.set_context(
            "sync_assets",
            {"asset_class": "us_equity", "status": "active"},
        )
        sentry_sdk.capture_exception(exc)


async def sync_assets(ctx: dict) -> dict:
    """Fetch Alpaca's active US-equity asset list and upsert into the
    local catalog. Runs daily at 10:00 UTC, before market open
    (US equities market opens 14:30 UTC / 9:30 AM ET).

    Outside of ARQ (e.g. manual dev trigger), ``ctx`` won't carry an
    ``alpaca`` service — we build a throwaway one and close it here.
    """
    broker: AlpacaBrokerService | None = ctx.get("alpaca")
    owns_broker = broker is None
    if broker is None:
        broker = AlpacaBrokerService()

    try:
        try:
            alpaca_assets = await broker.list_assets(
                status="active", asset_class="us_equity"
            )
        except AlpacaBrokerUnavailableError as exc:
            # Transient outage — the existing cache is still correct enough
            # to serve searches. Surface as a log warning and skip.
            logger.warning("assets_sync_alpaca_unavailable", error=str(exc))
            return {"status": "skipped", "reason": "alpaca_unavailable"}
        except Exception as exc:
            logger.error("assets_sync_failed", error=str(exc))
            _capture_with_scope(exc, failure_stage="alpaca_list_assets")
            raise

        # A legitimate active-us-equity feed is always 10k+ symbols. An
        # empty payload is almost certainly an Alpaca-side glitch; running
        # bulk_upsert with it would skip the soft-deactivate pass and
        # produce a misleading "deactivated" count. Treat as skip.
        if not alpaca_assets:
            logger.warning("assets_sync_empty_feed")
            return {"status": "skipped", "reason": "empty_feed"}

        rows: list[dict[str, Any]] = []
        malformed = 0
        for a in alpaca_assets:
            row = _to_asset_row(a)
            if row is None:
                malformed += 1
                continue
            rows.append(row)
        if malformed:
            logger.warning(
                "assets_sync_malformed_rows_skipped", count=malformed
            )

        input_symbols = {r["symbol"] for r in rows}

        try:
            async with async_session() as session:
                existing_result = await session.execute(
                    select(Asset.symbol, Asset.tradeable)
                )
                existing: dict[str, bool] = {
                    sym: tradeable for sym, tradeable in existing_result.all()
                }

                await AssetRepository.bulk_upsert(session, rows)
                await session.commit()
        except Exception as exc:
            logger.error("assets_sync_db_upsert_failed", error=str(exc))
            _capture_with_scope(exc, failure_stage="db_upsert")
            raise

        existing_symbols = set(existing.keys())
        new = len(input_symbols - existing_symbols)
        updated = len(input_symbols & existing_symbols)
        deactivated = sum(
            1
            for sym, tradeable in existing.items()
            if tradeable and sym not in input_symbols
        )

        summary = {
            "total": len(rows),
            "new": new,
            "updated": updated,
            "deactivated": deactivated,
        }
        logger.info("assets_synced", **summary)
        return summary
    finally:
        if owns_broker:
            await broker.close()
