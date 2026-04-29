"""Data access for `assets` — the searchable stock catalog.

`search` powers the ticker lookup UI (ILIKE over symbol + name, tradeable
only). `bulk_upsert` is the sync sink from the Alpaca asset feed: it
inserts new rows, updates rows whose name or exchange changed, and marks
symbols missing from the feed as `tradeable = False` (we never hard-delete
assets because referenced order_events/radar_items must remain resolvable).
"""

from typing import Any, Iterable

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset


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
          tradeable, logo_url, alpaca_asset_id). A symbol reappearing in
          the feed after a prior soft-deactivate is reactivated here.
        - `synced_at` is refreshed for every row present in the input so
          it reflects "last time we saw this symbol in the feed."
        - Flips `tradeable` to False for symbols in the DB but absent from
          the input (soft-deactivate).

        Symbols are uppercased before write so `"tsla"` and `"TSLA"` do
        not create distinct primary keys.

        Only flushes; the caller (typically an ARQ task) must commit.
        """
        rows = [
            {
                "symbol": a["symbol"].upper(),
                "name": a["name"],
                "exchange": a.get("exchange"),
                "tradeable": a.get("tradeable", True),
                "logo_url": a.get("logo_url"),
                "alpaca_asset_id": a.get("alpaca_asset_id"),
            }
            for a in assets
        ]
        if not rows:
            return

        # asyncpg caps prepared-statement parameters at 32,767. With 6
        # columns per row the live Alpaca feed (~12k symbols) overflows a
        # single INSERT, so chunk conservatively.
        _COLS_PER_ROW = 6
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
                    "logo_url": excluded.logo_url,
                    "alpaca_asset_id": excluded.alpaca_asset_id,
                    "synced_at": func.now(),
                },
            )
            await db.execute(stmt)

        input_symbols = [r["symbol"] for r in rows]
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
