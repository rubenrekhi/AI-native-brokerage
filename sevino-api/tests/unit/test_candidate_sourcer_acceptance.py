"""Acceptance: realistic universe + a few positions → 30–50 candidates
distributed across all four buckets."""

from app.services.radar_job.candidate_sourcer import (
    BUCKET_BROAD_NOTABLE,
    BUCKET_DIVERSIFICATION,
    BUCKET_OWNED_SECTOR,
    BUCKET_UPCOMING_EVENT,
    OWNED_SECTOR_CAP,
)

SECTORS = [
    "Technology", "Financials", "Healthcare", "Energy", "Industrials",
    "Consumer", "Utilities", "Materials", "RealEstate", "Communications",
    "Staples",
]


def _realistic_universe(radar_asset):
    gated = []
    for s_idx, sector in enumerate(SECTORS):
        for a_idx in range(6):
            mc = (len(SECTORS) - s_idx) * 1_000_000_000 - a_idx * 1_000_000
            gated.append(
                radar_asset(
                    f"{sector[:3].upper()}{a_idx}", sector=sector, market_cap=mc
                )
            )
    return gated


async def test_pool_spans_all_buckets_within_size_band(
    radar_asset, run_build_pool
):
    gated = _realistic_universe(radar_asset)
    # Hold the top name in two sectors; cheapest names in eight sectors have
    # upcoming events so they survive the higher-cap buckets.
    positions = [{"symbol": "TEC0"}, {"symbol": "FIN0"}]
    event_symbols = [f"{s[:3].upper()}5" for s in SECTORS[:8]]

    result = await run_build_pool(
        gated,
        positions=positions,
        owned_sectors={"Technology", "Financials"},
        earnings=[{"symbol": s, "date": "2026-06-10"} for s in event_symbols],
    )

    buckets = {c.bucket for c in result.pool}
    assert buckets == {
        BUCKET_OWNED_SECTOR,
        BUCKET_DIVERSIFICATION,
        BUCKET_UPCOMING_EVENT,
        BUCKET_BROAD_NOTABLE,
    }
    assert 30 <= len(result.pool) <= 50
    # No symbol appears under two buckets.
    symbols = [c.symbol for c in result.pool]
    assert len(symbols) == len(set(symbols))


async def test_owned_sector_bucket_caps_pool_for_user_holding_every_sector(
    radar_asset, run_build_pool
):
    gated = _realistic_universe(radar_asset)
    # Hold the top name in every sector — without the cap, owned_sector alone
    # would emit 11 * 4 = 44 candidates and push the pool past the band.
    positions = [{"symbol": f"{s[:3].upper()}0"} for s in SECTORS]

    result = await run_build_pool(
        gated, positions=positions, owned_sectors=set(SECTORS)
    )

    owned = [c for c in result.pool if c.bucket == BUCKET_OWNED_SECTOR]
    assert len(owned) <= OWNED_SECTOR_CAP
    assert len(result.pool) <= 50
