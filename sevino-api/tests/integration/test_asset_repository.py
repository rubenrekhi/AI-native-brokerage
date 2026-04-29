"""Integration tests for AssetRepository against real local Postgres."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.asset import AssetRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


@pytest.fixture(autouse=True)
async def _clean_assets(db_session: AsyncSession):
    # TRUNCATE is transactional in Postgres, so the per-test rollback in
    # db_session restores any rows synced by the worker (e.g. via
    # sync_assets cron). Without this, locally synced data collides with
    # test seeds and breaks ordering assertions. CASCADE keeps this safe
    # if other tables (order_events, radar_items) FK into assets.
    await db_session.execute(text("TRUNCATE assets RESTART IDENTITY CASCADE"))


async def _seed(db_session: AsyncSession, rows: list[dict]) -> None:
    """Direct INSERT so each test controls exact row state."""
    for row in rows:
        await db_session.execute(
            text(
                """
                INSERT INTO assets (symbol, name, exchange, tradeable)
                VALUES (:symbol, :name, :exchange, :tradeable)
                """
            ),
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "exchange": row.get("exchange"),
                "tradeable": row.get("tradeable", True),
            },
        )
    await db_session.flush()


class TestSearchOrdering:
    async def test_ticker_prefix_beats_name_match(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [
                {"symbol": "TSLA", "name": "Tesla Inc"},
                {"symbol": "AAPL", "name": "TSMC Holdings"},  # "ts" appears in name
            ],
        )

        results = await AssetRepository.search(db_session, "TS", limit=10)

        assert [a.symbol for a in results] == ["TSLA", "AAPL"]

    async def test_alphabetical_within_prefix_group(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [
                {"symbol": "TSLB", "name": "Tesla B"},
                {"symbol": "TSLA", "name": "Tesla A"},
                {"symbol": "TSCO", "name": "Tractor Supply"},
            ],
        )

        results = await AssetRepository.search(db_session, "TS", limit=10)

        assert [a.symbol for a in results] == ["TSCO", "TSLA", "TSLB"]


class TestSearchLimit:
    async def test_respects_limit(self, db_session: AsyncSession):
        await _seed(
            db_session,
            [
                {"symbol": f"TS{i:02d}", "name": f"Company {i}"} for i in range(10)
            ],
        )

        results = await AssetRepository.search(db_session, "TS", limit=3)

        assert len(results) == 3


class TestSearchTradeableFilter:
    async def test_excludes_untradeable(self, db_session: AsyncSession):
        await _seed(
            db_session,
            [
                {"symbol": "TSLA", "name": "Tesla", "tradeable": True},
                {"symbol": "TSDEAD", "name": "Delisted Co", "tradeable": False},
            ],
        )

        results = await AssetRepository.search(db_session, "TS", limit=10)

        assert [a.symbol for a in results] == ["TSLA"]


class TestBulkUpsert:
    async def test_inserts_new_assets(self, db_session: AsyncSession):
        await AssetRepository.bulk_upsert(
            db_session,
            [
                {
                    "symbol": "TSLA",
                    "name": "Tesla Inc",
                    "exchange": "NASDAQ",
                    "alpaca_asset_id": "alp_tsla",
                },
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "alpaca_asset_id": "alp_aapl",
                },
            ],
        )

        aapl = await AssetRepository.search(db_session, "AAPL", limit=1)
        assert aapl[0].symbol == "AAPL"
        assert aapl[0].alpaca_asset_id == "alp_aapl"
        tsla = await AssetRepository.search(db_session, "TSLA", limit=1)
        assert tsla[0].alpaca_asset_id == "alp_tsla"
        assert tsla[0].tradeable is True

    async def test_updates_changed_name_or_exchange(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "exchange": "NASDAQ"}],
        )

        await AssetRepository.bulk_upsert(
            db_session,
            [
                {
                    "symbol": "TSLA",
                    "name": "Tesla Motors",  # changed
                    "exchange": "NASDAQ",
                    "alpaca_asset_id": "alp_tsla",
                },
            ],
        )

        result = await db_session.execute(
            text("SELECT name, exchange FROM assets WHERE symbol = 'TSLA'")
        )
        name, exchange = result.one()
        assert name == "Tesla Motors"
        assert exchange == "NASDAQ"

    async def test_marks_removed_assets_untradeable(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [
                {"symbol": "TSLA", "name": "Tesla", "tradeable": True},
                {"symbol": "DEAD", "name": "Dead Co", "tradeable": True},
            ],
        )

        # DEAD is no longer in the input list → should be deactivated.
        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "exchange": "NASDAQ"}],
        )

        result = await db_session.execute(
            text("SELECT symbol, tradeable FROM assets ORDER BY symbol")
        )
        rows = {sym: flag for sym, flag in result.all()}
        assert rows == {"DEAD": False, "TSLA": True}

    async def test_reactivates_previously_deactivated_symbol(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "tradeable": False}],
        )

        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla"}],
        )

        result = await db_session.execute(
            text("SELECT tradeable FROM assets WHERE symbol = 'TSLA'")
        )
        assert result.scalar_one() is True

    async def test_empty_input_is_noop(self, db_session: AsyncSession):
        await _seed(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "tradeable": True}],
        )

        await AssetRepository.bulk_upsert(db_session, [])

        result = await db_session.execute(
            text("SELECT tradeable FROM assets WHERE symbol = 'TSLA'")
        )
        assert result.scalar_one() is True

    async def test_symbols_are_uppercased(self, db_session: AsyncSession):
        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "tsla", "name": "Tesla"}],
        )

        result = await db_session.execute(
            text("SELECT symbol FROM assets")
        )
        assert [row[0] for row in result.all()] == ["TSLA"]


class TestSearchWildcardEscaping:
    async def test_percent_in_query_is_literal(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [
                {"symbol": "TSLA", "name": "Tesla"},
                {"symbol": "PCT", "name": "100% Pure Co"},
            ],
        )

        # Without escaping, "%" would match everything.
        results = await AssetRepository.search(db_session, "100%", limit=10)

        assert [a.symbol for a in results] == ["PCT"]


class TestGetNamesBySymbols:
    async def test_returns_names_for_found_symbols_only(
        self, db_session: AsyncSession
    ):
        await _seed(
            db_session,
            [
                {"symbol": "AAPL", "name": "Apple Inc"},
                {"symbol": "TSLA", "name": "Tesla Inc"},
                {"symbol": "AMD", "name": "Advanced Micro Devices"},
            ],
        )

        names = await AssetRepository.get_names_by_symbols(
            db_session, ["AAPL", "TSLA", "XYZ"]
        )

        assert names == {"AAPL": "Apple Inc", "TSLA": "Tesla Inc"}

    async def test_empty_input_returns_empty_dict(
        self, db_session: AsyncSession
    ):
        names = await AssetRepository.get_names_by_symbols(db_session, [])
        assert names == {}

    async def test_all_missing_returns_empty_dict(
        self, db_session: AsyncSession
    ):
        await _seed(db_session, [{"symbol": "AAPL", "name": "Apple Inc"}])

        names = await AssetRepository.get_names_by_symbols(
            db_session, ["NONE", "NOPE"]
        )

        assert names == {}

    async def test_returns_untradeable_symbols_too(
        self, db_session: AsyncSession
    ):
        # Holdings need the name regardless of tradeability — a user may
        # still hold a delisted/frozen asset.
        await _seed(
            db_session,
            [{"symbol": "OLD", "name": "Delisted Co", "tradeable": False}],
        )

        names = await AssetRepository.get_names_by_symbols(
            db_session, ["OLD"]
        )

        assert names == {"OLD": "Delisted Co"}
