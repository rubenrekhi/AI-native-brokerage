"""diversification bucket: names from sectors the user has zero exposure to."""

from app.services.radar_job.candidate_sourcer import (
    BUCKET_DIVERSIFICATION,
    DIVERSIFICATION_CAP,
)

ALL_SECTORS = [
    "Technology", "Financials", "Healthcare", "Energy", "Industrials",
    "Consumer", "Utilities", "Materials", "RealEstate", "Communications",
    "Staples",
]


def _universe(radar_asset):
    gated = []
    for s_idx, sector in enumerate(ALL_SECTORS):
        for a_idx in range(3):
            mc = 1_000_000_000 * (100 - s_idx) + a_idx
            gated.append(
                radar_asset(
                    f"{sector[:3].upper()}{a_idx}", sector=sector, market_cap=mc
                )
            )
    return gated


async def test_holding_two_of_eleven_sectors_fills_from_missing(
    radar_asset, run_build_pool
):
    held = {"Technology", "Financials"}
    result = await run_build_pool(
        _universe(radar_asset),
        positions=[{"symbol": "TEC0"}, {"symbol": "FIN0"}],
        owned_sectors=held,
    )

    div = [c for c in result.pool if c.bucket == BUCKET_DIVERSIFICATION]

    assert len(div) == DIVERSIFICATION_CAP
    assert all(c.sector not in held for c in div)
    assert all(c.sector in ALL_SECTORS for c in div)
    # Spans several missing sectors rather than draining one.
    assert len({c.sector for c in div}) >= 2
