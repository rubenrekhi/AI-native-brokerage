"""Daily sync of the tradeable asset universe from Alpaca.

Alpaca is the source of truth for which symbols our users can trade. We
pull the full active US-equity list once per day, construct an FMP logo
URL from each symbol, and upsert into the local ``assets`` table that
powers the ticker search typeahead.

After the upsert, when an FMP client is available on ``ctx``, we enrich a
capped batch of assets with sector/industry/market_cap/ipo_date/country/
asset_type from FMP's profile endpoint. Enrichment is staggered (each
asset re-checked at most every 30 days) and rate-limited, so a full
backfill of the ~12k catalog spans a few daily runs.
"""

import asyncio
from datetime import date
from time import monotonic
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy import select

from app.database import async_session
from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.models.asset import Asset, AssetType
from app.repositories.asset import AssetRepository
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.fmp import FmpClient, none_if_blank

logger = structlog.get_logger(__name__)

FMP_LOGO_URL_TEMPLATE = "https://financialmodelingprep.com/image-stock/{symbol}.png"

ENRICHMENT_BATCH_LIMIT = 500
ENRICHMENT_COLD_START_BATCH_LIMIT = 100
ENRICHMENT_COLD_START_EXIT_THRESHOLD = 500
ENRICHMENT_CONCURRENCY = 10
ENRICHMENT_STALE_DAYS = 30
ENRICHMENT_REQUESTS_PER_MINUTE = 75
ENRICHMENT_COLD_START_REQUESTS_PER_MINUTE = 20


class _PerMinuteRateLimiter:
    """Paces request starts so a cold backfill doesn't burst FMP.

    The semaphore still controls in-flight concurrency; this limiter spaces
    out *starts* to keep us under a rough per-minute budget.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self._interval = 60 / requests_per_minute
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = monotonic()
            wait = max(0.0, self._next_slot - now)
            self._next_slot = max(now, self._next_slot) + self._interval
        if wait > 0:
            await asyncio.sleep(wait)


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
        # Default to True if Alpaca omits the field — matches the column
        # default and keeps the legacy "forward and let Alpaca decide" path
        # for any asset whose flag we can't determine.
        "fractionable": bool(alpaca_asset.get("fractionable", True)),
        "logo_url": FMP_LOGO_URL_TEMPLATE.format(symbol=symbol),
        "alpaca_asset_id": alpaca_asset.get("id"),
    }


def _to_bigint(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _asset_type(raw: dict[str, Any]) -> str:
    if raw.get("isEtf"):
        return AssetType.ETF
    if raw.get("isFund"):
        return AssetType.FUND
    return AssetType.STOCK


def _profile_to_enrichment(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "sector": none_if_blank(raw.get("sector")),
        "industry": none_if_blank(raw.get("industry")),
        "market_cap": _to_bigint(raw.get("marketCap")),
        "ipo_date": _parse_iso_date(raw.get("ipoDate")),
        "asset_type": _asset_type(raw),
        "country": none_if_blank(raw.get("country")),
    }


async def _enrich_assets(fmp: FmpClient) -> dict[str, int]:
    """Enrich a capped batch of stale/never-enriched assets from FMP.

    Returns counts of enriched / no-data / failed for observability.
    `MarketDataError` (402 = not in tier, or empty profile) is a permanent
    per-ticker gap: we stamp `enriched_at` anyway so the stagger doesn't
    keep retrying it. Transient upstream errors leave `enriched_at` NULL so
    the next run picks the symbol back up.
    """
    # Don't hold a pooled connection across the FMP fetch batch — it can run
    # tens of seconds at this concurrency. Read the symbol list, release the
    # session, fetch, then reopen only for the writes.
    async with async_session() as session:
        enriched_count = await AssetRepository.count_enriched_assets(
            session
        )
        cold_start = enriched_count < ENRICHMENT_COLD_START_EXIT_THRESHOLD
        batch_limit = (
            ENRICHMENT_COLD_START_BATCH_LIMIT
            if cold_start
            else ENRICHMENT_BATCH_LIMIT
        )
        symbols = await AssetRepository.list_symbols_needing_enrichment(
            session,
            limit=batch_limit,
            stale_days=ENRICHMENT_STALE_DAYS,
        )
    if not symbols:
        return {"enriched": 0, "no_data": 0, "failed": 0}

    semaphore = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    rate_limiter = _PerMinuteRateLimiter(
        ENRICHMENT_COLD_START_REQUESTS_PER_MINUTE
        if cold_start
        else ENRICHMENT_REQUESTS_PER_MINUTE
    )

    async def _fetch(symbol: str) -> tuple[str, dict[str, Any] | None, bool]:
        async with semaphore:
            await rate_limiter.acquire()
            try:
                raw = await fmp.profile(symbol)
            except MarketDataError:
                return symbol, None, True
            except (MarketDataUnavailableError, MarketDataUpstreamError):
                return symbol, None, False
            return symbol, _profile_to_enrichment(raw), True

    results = await asyncio.gather(*(_fetch(s) for s in symbols))

    enriched_rows: list[dict[str, Any]] = []
    no_data_symbols: list[str] = []
    failed = 0
    for symbol, mapped, stamp in results:
        if mapped is not None:
            enriched_rows.append({"symbol": symbol, **mapped})
        elif stamp:
            no_data_symbols.append(symbol)
        else:
            failed += 1

    async with async_session() as session:
        await AssetRepository.apply_enrichment(session, enriched_rows)
        await AssetRepository.mark_enriched(session, no_data_symbols)
        await session.commit()

    counts = {
        "enriched": len(enriched_rows),
        "no_data": len(no_data_symbols),
        "failed": failed,
    }
    logger.info(
        "assets_enriched",
        batch_limit=batch_limit,
        cold_start=cold_start,
        enriched_count=enriched_count,
        requests_per_minute=(
            ENRICHMENT_COLD_START_REQUESTS_PER_MINUTE
            if cold_start
            else ENRICHMENT_REQUESTS_PER_MINUTE
        ),
        **counts,
    )
    return counts


def _capture_with_scope(exc: Exception, *, failure_stage: str) -> None:
    # Structlog contextvars don't mirror onto the Sentry scope, so set
    # searchable tags explicitly for captures from this worker.
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
        if not rows:
            logger.warning("assets_sync_all_rows_malformed")
            return {"status": "skipped", "reason": "all_rows_malformed"}

        input_symbols = {r["symbol"] for r in rows}

        try:
            async with async_session() as session:
                async with session.begin():
                    existing_result = await session.execute(
                        select(Asset.symbol, Asset.tradeable)
                    )
                    existing: dict[str, bool] = {
                        sym: tradeable for sym, tradeable in existing_result.all()
                    }
                    await AssetRepository.bulk_upsert(session, rows)
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

        # Enrichment runs only when the worker supplied an FMP client on
        # ctx; it's a best-effort enhancement, so its failures must never
        # roll back or mask the catalog sync above.
        fmp: FmpClient | None = ctx.get("fmp")
        if fmp is not None:
            try:
                summary["enrichment"] = await _enrich_assets(fmp)
            except Exception as exc:
                logger.error("assets_enrichment_failed", error=str(exc))
                _capture_with_scope(exc, failure_stage="fmp_enrichment")

        return summary
    finally:
        if owns_broker:
            await broker.close()
