"""Data access for `assets` — the searchable stock catalog.

`search` powers the ticker lookup UI (ILIKE over symbol + name, tradeable
only). `bulk_upsert` is the sync sink from the Alpaca asset feed: it
inserts new rows, updates rows whose name or exchange changed, and marks
symbols missing from the feed as `tradeable = False` (we never hard-delete
assets because referenced order_events/radar_items must remain resolvable).
"""

from datetime import date, timedelta
from typing import Any, Iterable

import structlog
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

logger = structlog.get_logger(__name__)


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AssetRepository:

    @staticmethod
    async def search(
        db: AsyncSession, query: str, limit: int
    ) -> list[Asset]:
        """ILIKE prefix match on symbol, substring match on name.

        Ticker prefix hits rank above name hits; ties broken alphabetically
        by symbol. Untradeable assets are excluded.
        """
        escaped = _escape_ilike(query)
        prefix = f"{escaped}%"
        substring = f"%{escaped}%"

        prefix_match = Asset.symbol.ilike(prefix)
        rank = case((prefix_match, 0), else_=1)

        stmt = (
            select(Asset)
            .where(
                Asset.tradeable.is_(True),
                or_(prefix_match, Asset.name.ilike(substring)),
            )
            .order_by(rank, Asset.symbol)
            .limit(limit)
        )

        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_names_by_symbols(
        db: AsyncSession, symbols: list[str]
    ) -> dict[str, str]:
        """Return ``{symbol: name}`` for every symbol that exists in the table.

        Used by the holdings endpoint to attach human-readable names to
        Alpaca position rows, which only carry tickers. Missing symbols are
        simply absent from the result — callers decide how to default.
        """
        if not symbols:
            return {}
        result = await db.execute(
            select(Asset.symbol, Asset.name).where(Asset.symbol.in_(symbols))
        )
        return {row.symbol: row.name for row in result}

    @staticmethod
    async def get_by_symbol(db: AsyncSession, symbol: str) -> Asset | None:
        result = await db.execute(
            select(Asset).where(
                Asset.symbol == symbol.upper(),
                Asset.tradeable.is_(True),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def bulk_upsert(
        db: AsyncSession, assets: Iterable[dict[str, Any]]
    ) -> None:
        """Sync the catalog against a full asset list.

        - Inserts symbols not yet in the table.
        - Updates existing rows to match the input feed (name, exchange,
          tradeable, fractionable, logo_url, alpaca_asset_id). A symbol
          reappearing in the feed after a prior soft-deactivate is
          reactivated here.
        - `synced_at` is refreshed for every row present in the input so
          it reflects "last time we saw this symbol in the feed."
        - Flips `tradeable` to False for symbols in the DB but absent from
          the input (soft-deactivate).

        Symbols are uppercased before write so `"tsla"` and `"TSLA"` do
        not create distinct primary keys.

        Only flushes; the caller (typically an ARQ task) must commit.
        """
        rows_by_symbol: dict[str, dict[str, Any]] = {}
        duplicate_symbols = 0
        for asset in assets:
            symbol = asset["symbol"].upper()
            if symbol in rows_by_symbol:
                duplicate_symbols += 1
            rows_by_symbol[symbol] = {
                "symbol": symbol,
                "name": asset["name"],
                "exchange": asset.get("exchange"),
                "tradeable": asset.get("tradeable", True),
                "fractionable": asset.get("fractionable", True),
                "logo_url": asset.get("logo_url"),
                "alpaca_asset_id": asset.get("alpaca_asset_id"),
            }
        rows = list(rows_by_symbol.values())
        if not rows:
            return
        if duplicate_symbols:
            logger.warning(
                "assets_bulk_upsert_duplicate_symbols",
                duplicate_symbols=duplicate_symbols,
            )

        # Alpaca asset UUIDs are useful hints but not a stable enough key to
        # let them take the sync down. If the feed claims an existing UUID for
        # a different symbol, clear the stale holder first. If the feed itself
        # duplicates a UUID across multiple symbols, let the last-seen symbol
        # keep it and null the rest so the symbol-based upsert can still land.
        owner_by_asset_id: dict[str, str] = {}
        duplicate_asset_ids = 0
        for row in rows:
            asset_id = row["alpaca_asset_id"]
            if not asset_id:
                continue
            previous_owner = owner_by_asset_id.get(asset_id)
            if previous_owner is not None and previous_owner != row["symbol"]:
                duplicate_asset_ids += 1
            owner_by_asset_id[asset_id] = row["symbol"]
        if duplicate_asset_ids:
            for row in rows:
                asset_id = row["alpaca_asset_id"]
                if (
                    asset_id is not None
                    and owner_by_asset_id.get(asset_id) != row["symbol"]
                ):
                    row["alpaca_asset_id"] = None
            logger.warning(
                "assets_bulk_upsert_duplicate_alpaca_asset_ids_in_feed",
                duplicate_asset_ids=duplicate_asset_ids,
            )

        incoming_asset_ids = list(owner_by_asset_id.keys())
        if incoming_asset_ids:
            existing_holders = await db.execute(
                select(Asset.symbol, Asset.alpaca_asset_id).where(
                    Asset.alpaca_asset_id.in_(incoming_asset_ids)
                )
            )
            stale_symbols = [
                symbol
                for symbol, asset_id in existing_holders.all()
                if owner_by_asset_id.get(asset_id) != symbol
            ]
            if stale_symbols:
                await db.execute(
                    update(Asset)
                    .where(Asset.symbol.in_(stale_symbols))
                    .values(alpaca_asset_id=None)
                )
                logger.info(
                    "assets_bulk_upsert_cleared_stale_alpaca_asset_ids",
                    cleared_rows=len(stale_symbols),
                )

        # asyncpg caps prepared-statement parameters at 32,767. With 7
        # columns per row the live Alpaca feed (~12k symbols) overflows a
        # single INSERT, so chunk conservatively.
        _COLS_PER_ROW = 7
        chunk_size = 32_000 // _COLS_PER_ROW
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            stmt = insert(Asset).values(chunk)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=[Asset.symbol],
                set_={
                    "name": excluded.name,
                    "exchange": excluded.exchange,
                    "tradeable": excluded.tradeable,
                    "fractionable": excluded.fractionable,
                    "logo_url": excluded.logo_url,
                    "alpaca_asset_id": excluded.alpaca_asset_id,
                    "synced_at": func.now(),
                },
            )
            await db.execute(stmt)

        input_symbols = list(rows_by_symbol.keys())
        await db.execute(
            update(Asset)
            .where(
                and_(
                    Asset.symbol.notin_(input_symbols),
                    Asset.tradeable.is_(True),
                )
            )
            .values(tradeable=False, synced_at=func.now())
        )
        await db.flush()

    @staticmethod
    async def list_symbols_needing_enrichment(
        db: AsyncSession, *, limit: int, stale_days: int
    ) -> list[str]:
        """Symbols whose FMP enrichment is missing or stale.

        Never-enriched rows (NULL `enriched_at`) sort first, then oldest
        `enriched_at`, so a cold catalog hits every symbol once before
        re-touching anything. Capped at `limit` per call to bound FMP usage
        (full backfill takes a few days at the daily cap).
        """
        stale_cutoff = func.now() - timedelta(days=stale_days)
        stmt = (
            select(Asset.symbol)
            .where(
                or_(
                    Asset.enriched_at.is_(None),
                    Asset.enriched_at < stale_cutoff,
                )
            )
            .order_by(Asset.enriched_at.asc().nulls_first())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_enriched_assets(db: AsyncSession) -> int:
        """How many catalog rows currently carry enrichment ground truth."""
        result = await db.execute(
            select(func.count())
            .select_from(Asset)
            .where(Asset.enriched_at.is_not(None))
        )
        return int(result.scalar_one())

    @staticmethod
    async def apply_enrichment(
        db: AsyncSession, rows: Iterable[dict[str, Any]]
    ) -> None:
        """Write FMP profile fields and stamp `enriched_at` for each row.

        Each row carries `symbol` plus the enrichment columns. Only flushes;
        the caller commits.
        """
        for row in rows:
            await db.execute(
                update(Asset)
                .where(Asset.symbol == row["symbol"])
                .values(
                    sector=row.get("sector"),
                    industry=row.get("industry"),
                    market_cap=row.get("market_cap"),
                    ipo_date=row.get("ipo_date"),
                    asset_type=row.get("asset_type"),
                    country=row.get("country"),
                    enriched_at=func.now(),
                )
            )
        await db.flush()

    @staticmethod
    async def mark_enriched(db: AsyncSession, symbols: list[str]) -> None:
        """Stamp `enriched_at` without writing profile data.

        For symbols FMP has no profile for (402 = not in our tier, or an
        empty payload) — we record the attempt so the 30-day stagger doesn't
        retry them every single run. Only flushes; the caller commits.
        """
        if not symbols:
            return
        await db.execute(
            update(Asset)
            .where(Asset.symbol.in_(symbols))
            .values(enriched_at=func.now())
        )
        await db.flush()

    @staticmethod
    async def list_eligible_for_radar(
        db: AsyncSession,
        *,
        limit: int | None = None,
        min_market_cap: int | None = None,
        allowed_exchanges: Iterable[str] | None = None,
        allowed_asset_types: Iterable[str] | None = None,
        ipo_cutoff: "date | None" = None,
        exclude_country: str | None = None,
    ) -> list[Asset]:
        """Assets carrying FMP enrichment — the universe the radar quality
        gate (T2) and candidate sourcer (T3) query against.

        The enriched universe grows toward the full ~12k catalog, so callers
        should pass ``limit`` and/or push the gate's numeric/categorical
        filters into SQL via the optional kwargs. Doing so lets Postgres
        drop the ~80% of rows that fail the market-cap / exchange /
        asset-type / IPO-age / country checks before they ever hit
        SQLAlchemy hydration. Allow/deny-list filters (specific symbols and
        industries) stay in Python because they're cheap on the reduced
        set and easier to maintain as module constants.

        Ordered by symbol for a stable result under a limit.
        """
        conds = [Asset.enriched_at.is_not(None), Asset.tradeable.is_(True)]
        if min_market_cap is not None:
            conds.append(Asset.market_cap >= min_market_cap)
        if allowed_exchanges is not None:
            conds.append(Asset.exchange.in_(list(allowed_exchanges)))
        if allowed_asset_types is not None:
            conds.append(Asset.asset_type.in_(list(allowed_asset_types)))
        if ipo_cutoff is not None:
            # A NULL ipo_date is an FMP data gap on a qualifying large cap;
            # we admit it (matching the Python gate's policy) rather than
            # treat it as "too young."
            conds.append(or_(Asset.ipo_date.is_(None), Asset.ipo_date <= ipo_cutoff))
        if exclude_country is not None:
            conds.append(
                or_(Asset.country.is_(None), Asset.country != exclude_country)
            )

        stmt = select(Asset).where(*conds).order_by(Asset.symbol)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def sectors_for_symbols(
        db: AsyncSession, symbols: set[str]
    ) -> set[str]:
        """Distinct non-null sectors across the given symbols.

        Used by T3's `owned_sector` bucket to learn which sectors a user
        already holds. Symbols are uppercased to match catalog storage.
        """
        if not symbols:
            return set()
        upper = {s.upper() for s in symbols}
        result = await db.execute(
            select(Asset.sector)
            .where(Asset.symbol.in_(upper), Asset.sector.is_not(None))
            .distinct()
        )
        return {row[0] for row in result.all()}
