"""Unit tests for GET /v1/assets/search.

Repository is patched at the route's import path so the route wiring is
exercised without touching Postgres. Uses `authenticated_client` /
`client` fixtures from tests/conftest.py.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock


class TestSearchResponseShape:
    async def test_returns_list_of_symbol_name_logo(
        self, authenticated_client, mocker
    ):
        mocker.patch(
            "app.routes.assets.AssetRepository.search",
            new_callable=AsyncMock,
            return_value=[
                SimpleNamespace(
                    symbol="TSLA",
                    name="Tesla, Inc.",
                    logo_url="https://financialmodelingprep.com/image-stock/TSLA.png",
                ),
                SimpleNamespace(
                    symbol="TSM",
                    name="Taiwan Semiconductor Manufacturing Company Limited",
                    logo_url="https://financialmodelingprep.com/image-stock/TSM.png",
                ),
            ],
        )

        response = await authenticated_client.get("/v1/assets/search?q=TS&limit=10")

        assert response.status_code == 200
        assert response.json() == [
            {
                "symbol": "TSLA",
                "name": "Tesla, Inc.",
                "logo_url": "https://financialmodelingprep.com/image-stock/TSLA.png",
            },
            {
                "symbol": "TSM",
                "name": "Taiwan Semiconductor Manufacturing Company Limited",
                "logo_url": "https://financialmodelingprep.com/image-stock/TSM.png",
            },
        ]

    async def test_empty_results_returns_empty_array(
        self, authenticated_client, mocker
    ):
        mocker.patch(
            "app.routes.assets.AssetRepository.search",
            new_callable=AsyncMock,
            return_value=[],
        )

        response = await authenticated_client.get("/v1/assets/search?q=ZZZ")

        assert response.status_code == 200
        assert response.json() == []

    async def test_passes_query_and_limit_to_repository(
        self, authenticated_client, mocker
    ):
        search_mock = mocker.patch(
            "app.routes.assets.AssetRepository.search",
            new_callable=AsyncMock,
            return_value=[],
        )

        await authenticated_client.get("/v1/assets/search?q=AAPL&limit=5")

        args = search_mock.await_args
        assert args.args[1] == "AAPL"
        assert args.args[2] == 5

    async def test_default_limit_is_10(self, authenticated_client, mocker):
        search_mock = mocker.patch(
            "app.routes.assets.AssetRepository.search",
            new_callable=AsyncMock,
            return_value=[],
        )

        await authenticated_client.get("/v1/assets/search?q=A")

        assert search_mock.await_args.args[2] == 10


class TestAuth:
    async def test_without_token_returns_401(self, client):
        response = await client.get("/v1/assets/search?q=TS")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_ERROR"


class TestQueryValidation:
    async def test_missing_q_returns_422(self, authenticated_client):
        response = await authenticated_client.get("/v1/assets/search")
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_empty_q_returns_422(self, authenticated_client):
        response = await authenticated_client.get("/v1/assets/search?q=")
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_q_over_10_chars_returns_422(self, authenticated_client):
        response = await authenticated_client.get(
            "/v1/assets/search?q=" + "A" * 11
        )
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_limit_below_1_returns_422(self, authenticated_client):
        response = await authenticated_client.get("/v1/assets/search?q=TS&limit=0")
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"

    async def test_limit_above_50_returns_422(self, authenticated_client):
        response = await authenticated_client.get("/v1/assets/search?q=TS&limit=51")
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
