"""Integration test: static quality gate over real seeded asset rows.

Seeds an enriched universe (passing names + one row per failing rule),
reads it back through `AssetRepository.list_eligible_for_radar`, and asserts
the gate keeps exactly the eligible set and lands in a plausible band.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.repositories.asset import AssetRepository
from app.services.radar_job.quality_gate import StaticQualityGate
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

_NOW = datetime.now(timezone.utc)
_OLD_IPO = date(2000, 1, 1)


@pytest.fixture(autouse=True)
async def _clean_assets(db_session: AsyncSession):
    await db_session.execute(text("TRUNCATE assets RESTART IDENTITY CASCADE"))


async def _seed(db_session: AsyncSession, rows: list[dict]) -> None:
    db_session.add_all(
        Asset(
            symbol=row["symbol"],
            name=row.get("name", "Co"),
            exchange=row.get("exchange", "NASDAQ"),
            tradeable=row.get("tradeable", True),
            sector=row.get("sector", "Technology"),
            industry=row.get("industry", "Software"),
            market_cap=row.get("market_cap", 5_000_000_000),
            ipo_date=row.get("ipo_date", _OLD_IPO),
            asset_type=row.get("asset_type", "stock"),
            country=row.get("country", "US"),
            enriched_at=row.get("enriched_at", _NOW),
        )
        for row in rows
    )
    await db_session.flush()


async def test_gate_keeps_eligible_universe(db_session: AsyncSession):
    passing = [{"symbol": f"GOOD{i:03d}"} for i in range(120)]
    passing_etf = {"symbol": "SPY", "asset_type": "etf", "exchange": "ARCA"}

    failing = [
        {"symbol": "LOWCAP", "market_cap": 1_000_000_000},
        {"symbol": "NOCAP", "market_cap": None},
        {"symbol": "RECENT", "ipo_date": date.today() - timedelta(days=30)},
        {"symbol": "OTCX", "exchange": "OTC"},
        {"symbol": "FUNDX", "asset_type": "fund"},
        {"symbol": "NOTYPE", "asset_type": None},
        {"symbol": "ARKK", "asset_type": "etf", "exchange": "ARCA"},
        {"symbol": "TQQQ", "asset_type": "stock"},
        {"symbol": "CANNA", "industry": "Cannabis"},
        {"symbol": "CNADR", "country": "CN"},
        {"symbol": "DELISTED", "tradeable": False},
    ]

    await _seed(db_session, [*passing, passing_etf, *failing])

    eligible = await AssetRepository.list_eligible_for_radar(db_session)
    gated = StaticQualityGate.filter(eligible)
    symbols = {a.symbol for a in gated}

    assert len(gated) == 121
    assert "SPY" in symbols
    assert "GOOD000" in symbols
    assert symbols.isdisjoint(
        {row["symbol"] for row in failing}
    )
    # Plausible-band sanity check from the ticket's acceptance criteria.
    assert 100 < len(gated) < 5000
