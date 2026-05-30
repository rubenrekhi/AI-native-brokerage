"""Integration tests for AssetRepository against real local Postgres."""

from datetime import datetime, timedelta, timezone

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

    async def test_persists_fractionable_flag_on_insert(
        self, db_session: AsyncSession
    ):
        await AssetRepository.bulk_upsert(
            db_session,
            [
                {"symbol": "TSLA", "name": "Tesla", "fractionable": True},
                {"symbol": "ILLQ", "name": "Illiquid Co", "fractionable": False},
            ],
        )

        result = await db_session.execute(
            text(
                "SELECT symbol, fractionable FROM assets ORDER BY symbol"
            )
        )
        rows = {sym: frac for sym, frac in result.all()}
        assert rows == {"ILLQ": False, "TSLA": True}

    async def test_updates_fractionable_flag_on_re_sync(
        self, db_session: AsyncSession
    ):
        # Asset starts fractionable; Alpaca later flips it to whole-shares-only
        # (e.g. after a delisting event). bulk_upsert must reflect the change.
        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "fractionable": True}],
        )

        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla", "fractionable": False}],
        )

        result = await db_session.execute(
            text("SELECT fractionable FROM assets WHERE symbol = 'TSLA'")
        )
        assert result.scalar_one() is False

    async def test_defaults_fractionable_true_when_field_missing(
        self, db_session: AsyncSession
    ):
        # Mirrors the column default — older callers that don't pass
        # `fractionable` should land on True so behavior is unchanged.
        await AssetRepository.bulk_upsert(
            db_session,
            [{"symbol": "TSLA", "name": "Tesla"}],
        )

        result = await db_session.execute(
            text("SELECT fractionable FROM assets WHERE symbol = 'TSLA'")
        )
        assert result.scalar_one() is True


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


async def _seed_enriched(
    db_session: AsyncSession, rows: list[dict]
) -> None:
    """Insert assets with enrichment columns set, for radar/enrichment tests."""
    for row in rows:
        await db_session.execute(
            text(
                """
                INSERT INTO assets
                    (symbol, name, tradeable, sector, enriched_at)
                VALUES
                    (:symbol, :name, :tradeable, :sector, :enriched_at)
                """
            ),
            {
                "symbol": row["symbol"],
                "name": row.get("name", "Co"),
                "tradeable": row.get("tradeable", True),
                "sector": row.get("sector"),
                "enriched_at": row.get("enriched_at"),
            },
        )
    await db_session.flush()


def _days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


class TestListSymbolsNeedingEnrichment:
    async def test_includes_never_and_stale_excludes_fresh(
        self, db_session: AsyncSession
    ):
        await _seed_enriched(
            db_session,
            [
                {"symbol": "NEVER", "enriched_at": None},
                {"symbol": "STALE", "enriched_at": _days_ago(40)},
                {"symbol": "FRESH", "enriched_at": _days_ago(5)},
            ],
        )

        symbols = await AssetRepository.list_symbols_needing_enrichment(
            db_session, limit=10, stale_days=30
        )

        assert set(symbols) == {"NEVER", "STALE"}

    async def test_prioritizes_never_then_oldest(
        self, db_session: AsyncSession
    ):
        await _seed_enriched(
            db_session,
            [
                {"symbol": "OLDER", "enriched_at": _days_ago(50)},
                {"symbol": "NEVER", "enriched_at": None},
                {"symbol": "OLD", "enriched_at": _days_ago(40)},
            ],
        )

        symbols = await AssetRepository.list_symbols_needing_enrichment(
            db_session, limit=10, stale_days=30
        )

        # NULL first, then oldest enriched_at ascending.
        assert symbols == ["NEVER", "OLDER", "OLD"]

    async def test_respects_limit(self, db_session: AsyncSession):
        await _seed_enriched(
            db_session,
            [{"symbol": f"S{i:02d}", "enriched_at": None} for i in range(10)],
        )

        symbols = await AssetRepository.list_symbols_needing_enrichment(
            db_session, limit=3, stale_days=30
        )

        assert len(symbols) == 3


class TestListEligibleForRadar:
    async def test_filters_out_non_enriched_rows(
        self, db_session: AsyncSession
    ):
        await _seed_enriched(
            db_session,
            [
                {"symbol": "ENR1", "enriched_at": _days_ago(1)},
                {"symbol": "ENR2", "enriched_at": _days_ago(2)},
                {"symbol": "RAW", "enriched_at": None},
            ],
        )

        eligible = await AssetRepository.list_eligible_for_radar(db_session)

        assert {a.symbol for a in eligible} == {"ENR1", "ENR2"}


class TestSectorsForSymbols:
    async def test_returns_distinct_non_null_sectors(
        self, db_session: AsyncSession
    ):
        await _seed_enriched(
            db_session,
            [
                {"symbol": "AAPL", "sector": "Technology", "enriched_at": _days_ago(1)},
                {"symbol": "MSFT", "sector": "Technology", "enriched_at": _days_ago(1)},
                {"symbol": "JPM", "sector": "Financials", "enriched_at": _days_ago(1)},
                {"symbol": "XYZ", "sector": None, "enriched_at": _days_ago(1)},
            ],
        )

        sectors = await AssetRepository.sectors_for_symbols(
            db_session, {"AAPL", "MSFT", "JPM", "XYZ"}
        )

        assert sectors == {"Technology", "Financials"}

    async def test_uppercases_input_symbols(self, db_session: AsyncSession):
        await _seed_enriched(
            db_session,
            [{"symbol": "AAPL", "sector": "Technology", "enriched_at": _days_ago(1)}],
        )

        sectors = await AssetRepository.sectors_for_symbols(
            db_session, {"aapl"}
        )

        assert sectors == {"Technology"}

    async def test_empty_input_returns_empty_set(
        self, db_session: AsyncSession
    ):
        assert await AssetRepository.sectors_for_symbols(db_session, set()) == set()
