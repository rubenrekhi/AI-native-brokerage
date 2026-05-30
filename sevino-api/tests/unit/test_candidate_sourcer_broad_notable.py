"""broad_notable bucket: top names by market cap; always-on fallback."""

from app.services.radar_job.candidate_sourcer import (
    BROAD_NOTABLE_CAP,
    BUCKET_BROAD_NOTABLE,
    _broad_notable_bucket,
)


def test_returns_top_ten_sorted_by_market_cap(radar_asset):
    gated = [
        radar_asset(f"S{i}", sector="Technology", market_cap=i * 1_000_000_000)
        for i in range(1, 21)
    ]

    out = _broad_notable_bucket(gated, exclude=set())

    assert len(out) == BROAD_NOTABLE_CAP
    caps = [c.market_cap for c in out]
    assert caps == sorted(caps, reverse=True)
    assert [c.symbol for c in out][:3] == ["S20", "S19", "S18"]
    assert all(c.bucket == BUCKET_BROAD_NOTABLE for c in out)


async def test_always_populated_for_new_user(radar_asset, run_build_pool):
    gated = [
        radar_asset(f"S{i}", sector="Technology", market_cap=i * 1_000_000_000)
        for i in range(1, 21)
    ]

    result = await run_build_pool(gated, account_status="SUBMITTED")

    notable = [c for c in result.pool if c.bucket == BUCKET_BROAD_NOTABLE]
    assert notable, "broad_notable must always fire as the new-user fallback"
