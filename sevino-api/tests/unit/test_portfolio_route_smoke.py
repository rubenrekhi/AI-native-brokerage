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
