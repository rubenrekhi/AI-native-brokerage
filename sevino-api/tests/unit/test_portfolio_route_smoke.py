"""Smoke tests for the /v1/portfolio router.

Heavy coverage lives in `tests/integration/test_portfolio_snapshot.py`
(B1.4). This file confirms the route is mounted with the right schema.
"""


class TestPortfolioRouteRegistration:
    async def test_snapshot_route_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        assert "/v1/portfolio/snapshot" in spec["paths"]
        snapshot = spec["paths"]["/v1/portfolio/snapshot"]
        assert "get" in snapshot
        assert snapshot["get"]["tags"] == ["portfolio"]

    async def test_snapshot_response_model_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        success = spec["paths"]["/v1/portfolio/snapshot"]["get"]["responses"]["200"]
        ref = success["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/PortfolioSnapshotResponse")

    async def test_holdings_route_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        assert "/v1/portfolio/holdings" in spec["paths"]
        holdings = spec["paths"]["/v1/portfolio/holdings"]
        assert "get" in holdings
        assert holdings["get"]["tags"] == ["portfolio"]

    async def test_holdings_response_model_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        success = spec["paths"]["/v1/portfolio/holdings"]["get"]["responses"]["200"]
        ref = success["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/HoldingsResponse")

    async def test_history_route_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        assert "/v1/portfolio/history" in spec["paths"]
        history = spec["paths"]["/v1/portfolio/history"]
        assert "get" in history
        assert history["get"]["tags"] == ["portfolio"]

    async def test_history_response_model_in_openapi(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        success = spec["paths"]["/v1/portfolio/history"]["get"]["responses"]["200"]
        ref = success["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/PortfolioHistoryResponse")

    async def test_history_range_param_is_required_enum(self, client):
        response = await client.get("/openapi.json")
        spec = response.json()

        params = spec["paths"]["/v1/portfolio/history"]["get"]["parameters"]
        range_param = next(p for p in params if p["name"] == "range")
        assert range_param["in"] == "query"
        assert range_param["required"] is True
        # Resolves through the PortfolioRange enum schema.
        ref = range_param["schema"]["$ref"]
        assert ref.endswith("/PortfolioRange")
        enum_values = spec["components"]["schemas"]["PortfolioRange"]["enum"]
        assert set(enum_values) == {
            "1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL",
        }
