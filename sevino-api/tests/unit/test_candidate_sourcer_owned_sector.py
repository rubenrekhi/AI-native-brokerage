"""owned_sector bucket: top names in sectors the user already holds."""

from app.services.radar_job.candidate_sourcer import (
    BUCKET_OWNED_SECTOR,
    OWNED_SECTOR_PER_SECTOR,
)


async def test_two_held_sectors_return_top_four_each(radar_asset, run_build_pool):
    gated = [radar_asset("OWN_TECH", sector="Technology")]
    gated += [
        radar_asset(f"T{i}", sector="Technology", market_cap=mc)
        for i, mc in enumerate([90, 80, 70, 60, 50], start=1)
    ]
    gated += [radar_asset("OWN_FIN", sector="Financials")]
    gated += [
        radar_asset(f"F{i}", sector="Financials", market_cap=mc)
        for i, mc in enumerate([95, 85, 75, 65, 55], start=1)
    ]

    result = await run_build_pool(
        gated,
        positions=[{"symbol": "OWN_TECH"}, {"symbol": "OWN_FIN"}],
        owned_sectors={"Technology", "Financials"},
    )

    owned = [c for c in result.pool if c.bucket == BUCKET_OWNED_SECTOR]
    symbols = {c.symbol for c in owned}

    assert len(owned) == 2 * OWNED_SECTOR_PER_SECTOR
    assert symbols == {"T1", "T2", "T3", "T4", "F1", "F2", "F3", "F4"}
    assert "OWN_TECH" not in symbols
    assert "OWN_FIN" not in symbols
    assert {c.sector for c in owned} == {"Technology", "Financials"}
