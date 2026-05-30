"""Pool excludes symbols already on the user's radar (any state) and owned."""


async def test_existing_radar_and_owned_symbols_never_appear(
    radar_asset, run_build_pool
):
    gated = [
        radar_asset("NVDA", sector="Technology", market_cap=50),
        radar_asset("AAPL", sector="Technology", market_cap=40),
        radar_asset("MSFT", sector="Technology", market_cap=30),
        radar_asset("JPM", sector="Financials", market_cap=20),
    ]

    result = await run_build_pool(
        gated,
        positions=[{"symbol": "JPM"}],
        owned_sectors={"Financials"},
        existing_radar={"NVDA"},
    )

    symbols = {c.symbol for c in result.pool}
    assert "NVDA" not in symbols  # already on radar
    assert "JPM" not in symbols  # currently owned
    assert {"AAPL", "MSFT"} <= symbols


async def test_existing_radar_excluded_case_insensitively(
    radar_asset, run_build_pool
):
    gated = [radar_asset("AAPL", sector="Technology", market_cap=40)]

    result = await run_build_pool(gated, existing_radar={"aapl"})

    assert all(c.symbol != "AAPL" for c in result.pool)


async def test_lowercase_gated_symbol_excluded_case_insensitively(
    radar_asset, run_build_pool
):
    gated = [radar_asset("aapl", sector="Technology", market_cap=40)]

    result = await run_build_pool(gated, existing_radar={"AAPL"})

    assert result.pool == []
