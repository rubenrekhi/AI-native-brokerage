"""No positions → owned_sector stays empty; other buckets still fire."""

from app.services.radar_job.candidate_sourcer import (
    BUCKET_DIVERSIFICATION,
    BUCKET_OWNED_SECTOR,
)


def _multi_sector(radar_asset):
    return [
        radar_asset("AAPL", sector="Technology", market_cap=90),
        radar_asset("MSFT", sector="Technology", market_cap=80),
        radar_asset("JPM", sector="Financials", market_cap=70),
        radar_asset("XOM", sector="Energy", market_cap=60),
    ]


async def test_active_account_with_empty_positions(radar_asset, run_build_pool):
    result = await run_build_pool(_multi_sector(radar_asset), positions=[])

    buckets = {c.bucket for c in result.pool}
    assert not any(c.bucket == BUCKET_OWNED_SECTOR for c in result.pool)
    assert BUCKET_DIVERSIFICATION in buckets
    assert result.pool, "non-owned buckets must still populate the pool"
    result.alpaca.list_positions.assert_awaited_once()


async def test_submitted_account_skips_alpaca(radar_asset, run_build_pool):
    result = await run_build_pool(
        _multi_sector(radar_asset), account_status="SUBMITTED"
    )

    assert not any(c.bucket == BUCKET_OWNED_SECTOR for c in result.pool)
    assert result.pool, "non-owned buckets must still populate the pool"
    result.alpaca.list_positions.assert_not_awaited()
