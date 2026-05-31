"""End-to-end smoke test for the T5 radar orchestrator.

Drives the full pipeline against a real local Postgres: seeds an enriched
asset universe, plants a mixed bag of prior radar rows (favorited AI,
unfavorited AI, user_added), stubs Alpaca/FMP/Anthropic, and verifies
the orchestrator (a) rotates only the unfavorited AI rows, (b) inserts
the new batch with the right metadata, and (c) advances
``next_radar_refresh_at`` by 7 days from the prior anchor.

The candidate sourcer is left real so this catches contract drift
between sourcer ↔ orchestrator (bucket strings, exclude-set semantics);
only the external IO at the edges is mocked.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.models.asset import Asset, AssetType
from app.models.radar_item import RadarItem
from app.models.user_profile import UserProfile
from app.services.radar_job.llm import RadarPick
from app.services.radar_job.orchestrator import generate_radar_batch
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync, reason="Local Postgres not running"
)


# Sixteen sectors × 3 megacaps each = 48 enriched rows. Generous enough
# that the gate keeps them all, the sourcer hits the 10-pool floor in
# every shape we test, and the LLM mock can choose from a known pool.
_SECTORS = [
    "Technology", "Financials", "Healthcare", "Energy",
    "Industrials", "Consumer Discretionary", "Consumer Staples", "Utilities",
    "Materials", "Real Estate", "Communication Services", "Insurance",
    "Transportation", "Media", "Semiconductors", "Software",
]


def _seed_symbol(idx: int, sector_idx: int) -> str:
    # Bounded uppercase ticker — keeps the unique constraint happy and
    # mirrors how `assets.symbol` is stored upstream.
    return f"S{sector_idx:02d}T{idx}"


async def _seed_universe(db_session) -> list[Asset]:
    assets: list[Asset] = []
    for s_idx, sector in enumerate(_SECTORS):
        for a_idx in range(3):
            asset = Asset(
                symbol=_seed_symbol(a_idx, s_idx),
                name=f"{sector} Company {a_idx}",
                exchange="NYSE",
                tradeable=True,
                fractionable=True,
                sector=sector,
                # Distinct caps per sector so deterministic-by-mkt-cap
                # sourcing is stable.
                market_cap=50_000_000_000 - (s_idx * 1_000_000_000) - a_idx,
                asset_type=AssetType.STOCK.value,
                ipo_date=date(2010, 1, 1),
                country="US",
                enriched_at=datetime.now(timezone.utc),
            )
            db_session.add(asset)
            assets.append(asset)
    await db_session.flush()
    return assets


def _fake_llm_picks(symbols: list[str]) -> list[RadarPick]:
    """Build five canonical picks the orchestrator will accept.

    Symbols come from the gated universe so the validator's "must be in
    pool" check passes; bucket is set to ``broad_notable`` because the
    seeded user has no positions or favorites and the sourcer tags the
    biggest megacaps under that bucket.
    """
    return [
        RadarPick(
            symbol=symbol,
            label=f"Notable mid/large-cap operator: {symbol}.",
            bucket="broad_notable",
            relevance=0.9 - 0.05 * idx,
        )
        for idx, symbol in enumerate(symbols)
    ]


class _StubLLM:
    """Drop-in for ``RadarLLM`` — the orchestrator only calls ``pick``."""

    def __init__(self, picks_factory):
        self._picks_factory = picks_factory
        self.calls: list[tuple] = []

    async def pick(self, pool, user_ctx):
        self.calls.append((pool, user_ctx))
        return self._picks_factory(pool)


@pytest.fixture
async def seeded_universe(db_session):
    return await _seed_universe(db_session)


@pytest.fixture
def stub_alpaca():
    alpaca = AsyncMock()
    alpaca.list_positions = AsyncMock(return_value=[])
    return alpaca


@pytest.fixture
def stub_fmp_and_redis():
    """The event bucket calls FMP through the cached events client; mock
    both so no network reach happens. Returning empty lists is enough —
    the seeded universe is big enough to fill the pool from the
    sector / notable buckets alone."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    redis.set = AsyncMock()
    fmp = AsyncMock()
    fmp.earnings_calendar = AsyncMock(return_value=[])
    fmp.dividend_calendar = AsyncMock(return_value=[])
    return fmp, redis


def _patch_radar_llm(monkeypatch, stub: _StubLLM):
    import app.services.radar_job.orchestrator as orchestrator_mod

    monkeypatch.setattr(
        orchestrator_mod, "RadarLLM", lambda _anthropic: stub
    )


async def test_orchestrator_persists_batch_with_bucket_expiry_relevance(
    db_session, test_user, seeded_universe, stub_alpaca, stub_fmp_and_redis,
    monkeypatch,
):
    fmp, redis = stub_fmp_and_redis

    # Pick the five symbols the sourcer is most likely to surface (top
    # market cap → first three sectors). They're real seeded rows so the
    # validator + sourcer + writer all see consistent inputs.
    target_symbols = [_seed_symbol(0, i) for i in range(5)]

    stub = _StubLLM(lambda _pool: _fake_llm_picks(target_symbols))
    _patch_radar_llm(monkeypatch, stub)

    result = await generate_radar_batch(
        test_user,
        db_session,
        alpaca=stub_alpaca,
        fmp=fmp,
        redis=redis,
        anthropic=AsyncMock(),
    )

    assert result.picks_count == 5
    assert stub.calls, "orchestrator should have called RadarLLM.pick"

    rows = (
        await db_session.execute(
            select(RadarItem).where(RadarItem.user_id == test_user)
        )
    ).scalars().all()
    assert len(rows) == 5
    by_symbol = {r.symbol: r for r in rows}
    for symbol in target_symbols:
        row = by_symbol[symbol]
        assert row.source == "ai_generated"
        assert row.is_favorited is False
        assert row.bucket == "broad_notable"
        assert row.context_blurb is not None
        assert row.relevance_score is not None
        # `expires_at` mirrors `next_radar_refresh_at` exactly — that's
        # the rotation contract: a row dies the moment its replacement
        # batch is due.
        assert row.expires_at == result.next_refresh_at


async def test_orchestrator_rotates_unfavorited_ai_and_preserves_others(
    db_session, test_user, seeded_universe, stub_alpaca, stub_fmp_and_redis,
    monkeypatch,
):
    fmp, redis = stub_fmp_and_redis

    # Prior week's batch: two unfavorited AI rows (should rotate out), one
    # favorited AI row (the watchlist — keep), one user_added row (keep
    # always). Use symbols outside the new batch so the unique constraint
    # never has to mediate.
    db_session.add(RadarItem(
        user_id=test_user, symbol="OLDAI1",
        source="ai_generated", is_favorited=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    ))
    db_session.add(RadarItem(
        user_id=test_user, symbol="OLDAI2",
        source="ai_generated", is_favorited=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=3),
    ))
    db_session.add(RadarItem(
        user_id=test_user, symbol="FAVAI",
        source="ai_generated", is_favorited=True,
        expires_at=None,
    ))
    db_session.add(RadarItem(
        user_id=test_user, symbol="MINE",
        source="user_added", is_favorited=True,
        expires_at=None,
    ))
    await db_session.flush()

    target_symbols = [_seed_symbol(0, i) for i in range(5)]
    stub = _StubLLM(lambda _pool: _fake_llm_picks(target_symbols))
    _patch_radar_llm(monkeypatch, stub)

    await generate_radar_batch(
        test_user,
        db_session,
        alpaca=stub_alpaca,
        fmp=fmp,
        redis=redis,
        anthropic=AsyncMock(),
    )

    rows = (
        await db_session.execute(
            select(RadarItem.symbol).where(RadarItem.user_id == test_user)
        )
    ).scalars().all()
    remaining = set(rows)
    assert "OLDAI1" not in remaining
    assert "OLDAI2" not in remaining
    # The watchlist (favorited AI) and user-added rows survived rotation —
    # the invariant T5 has to guarantee.
    assert "FAVAI" in remaining
    assert "MINE" in remaining
    # All five new picks landed alongside the two preserved rows.
    assert set(target_symbols).issubset(remaining)


async def test_orchestrator_advances_next_refresh_anchor_by_seven_days(
    db_session, test_user, seeded_universe, stub_alpaca, stub_fmp_and_redis,
    monkeypatch,
):
    fmp, redis = stub_fmp_and_redis

    # A past anchor — orchestrator will treat the user as due for rotation
    # and advance by exactly 7d from this value (day-of-week preserved).
    prior_anchor = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :v WHERE id = :id"
        ),
        {"v": prior_anchor, "id": test_user},
    )
    await db_session.flush()

    target_symbols = [_seed_symbol(0, i) for i in range(5)]
    stub = _StubLLM(lambda _pool: _fake_llm_picks(target_symbols))
    _patch_radar_llm(monkeypatch, stub)

    result = await generate_radar_batch(
        test_user,
        db_session,
        alpaca=stub_alpaca,
        fmp=fmp,
        redis=redis,
        anthropic=AsyncMock(),
    )

    assert result.next_refresh_at == prior_anchor + timedelta(days=7)
    # Round-trip through the DB to catch a regression where the function
    # returned the right value but forgot to persist.
    persisted = (
        await db_session.execute(
            select(UserProfile.next_radar_refresh_at).where(
                UserProfile.id == test_user
            )
        )
    ).scalar_one()
    assert persisted == prior_anchor + timedelta(days=7)


async def test_orchestrator_raises_when_pool_is_too_small(
    db_session, test_user, stub_alpaca, stub_fmp_and_redis, monkeypatch,
):
    # Skip the universe-seeding fixture — empty `assets` means the
    # candidate sourcer returns an empty pool and the orchestrator must
    # bail before calling the LLM (or writing anything).
    fmp, redis = stub_fmp_and_redis
    from app.services.radar_job import RadarJobError

    stub = _StubLLM(lambda _pool: _fake_llm_picks([]))
    _patch_radar_llm(monkeypatch, stub)

    with pytest.raises(RadarJobError) as exc:
        await generate_radar_batch(
            test_user,
            db_session,
            alpaca=stub_alpaca,
            fmp=fmp,
            redis=redis,
            anthropic=AsyncMock(),
        )
    assert exc.value.code == "pool_too_small"
    assert not stub.calls, "LLM must not be called when the pool is too small"


async def test_orchestrator_skips_when_anchor_is_already_in_future(
    db_session, test_user, seeded_universe, stub_alpaca, stub_fmp_and_redis,
    monkeypatch,
):
    # Simulates a concurrent worker having already rotated this user: the
    # anchor is fresh (~7d out). The orchestrator must bail without
    # touching radar_items or advancing the anchor further.
    fmp, redis = stub_fmp_and_redis
    fresh_anchor = datetime.now(timezone.utc) + timedelta(days=7)
    await db_session.execute(
        text(
            "UPDATE user_profiles SET next_radar_refresh_at = :v WHERE id = :id"
        ),
        {"v": fresh_anchor, "id": test_user},
    )
    await db_session.flush()

    # Pre-existing AI row from the "first" rotation — must survive the
    # second orchestrator's skip path.
    db_session.add(RadarItem(
        user_id=test_user, symbol="PRIORAI",
        source="ai_generated", is_favorited=False,
        expires_at=fresh_anchor,
    ))
    await db_session.flush()

    target_symbols = [_seed_symbol(0, i) for i in range(5)]
    stub = _StubLLM(lambda _pool: _fake_llm_picks(target_symbols))
    _patch_radar_llm(monkeypatch, stub)

    from app.services.radar_job import RadarJobError

    with pytest.raises(RadarJobError) as exc:
        await generate_radar_batch(
            test_user,
            db_session,
            alpaca=stub_alpaca,
            fmp=fmp,
            redis=redis,
            anthropic=AsyncMock(),
        )
    assert exc.value.code == "already_rotated"

    # Nothing got rotated: the prior row survives, no new rows landed,
    # anchor unchanged.
    rows = (
        await db_session.execute(
            select(RadarItem.symbol).where(RadarItem.user_id == test_user)
        )
    ).scalars().all()
    assert set(rows) == {"PRIORAI"}

    persisted = (
        await db_session.execute(
            select(UserProfile.next_radar_refresh_at).where(
                UserProfile.id == test_user
            )
        )
    ).scalar_one()
    assert persisted == fresh_anchor
