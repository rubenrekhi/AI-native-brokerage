"""Smoke tests for the /v1/portfolio router.

Heavy coverage lives in `tests/integration/test_portfolio_*.py`. This
file only confirms the routes are mounted, since their absence would
otherwise surface as a stack of 404s in the integration suite.
"""


class TestPortfolioRouteRegistration:
    async def test_all_portfolio_routes_are_mounted(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        assert "/v1/portfolio/snapshot" in spec["paths"]
        assert "/v1/portfolio/holdings" in spec["paths"]
        assert "/v1/portfolio/history" in spec["paths"]

    async def test_history_range_param_enum_is_complete(self, client):
        # Hard-coded list elsewhere (iOS, range_to_alpaca_params) — guards
        # against silent enum drift.
        response = await client.get("/openapi.json")
        spec = response.json()

        enum_values = spec["components"]["schemas"]["PortfolioRange"]["enum"]
        assert set(enum_values) == {
            "1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL",
        }
