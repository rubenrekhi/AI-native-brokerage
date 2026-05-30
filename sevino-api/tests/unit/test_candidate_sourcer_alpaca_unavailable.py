"""Alpaca unavailable → degrade to empty positions, never raise."""

from app.services.radar_job.candidate_sourcer import BUCKET_OWNED_SECTOR


async def test_alpaca_error_degrades_to_empty_positions(
    radar_asset, run_build_pool
):
    gated = [
        radar_asset("AAPL", sector="Technology", market_cap=90),
        radar_asset("JPM", sector="Financials", market_cap=70),
        radar_asset("XOM", sector="Energy", market_cap=60),
    ]

    result = await run_build_pool(gated, alpaca_unavailable=True)

    assert result.pool, "pipeline must continue in degraded mode"
    assert not any(c.bucket == BUCKET_OWNED_SECTOR for c in result.pool)
    result.alpaca.list_positions.assert_awaited_once()
