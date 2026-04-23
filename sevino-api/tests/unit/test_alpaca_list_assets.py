import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"


def _load(name: str) -> list[dict]:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _make_service(handler) -> AlpacaBrokerService:
    service = AlpacaBrokerService()
    service._access_token = "fake-access-token"
    service._token_expires_at = time.time() + 3600
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=30.0
    )
    return service


class TestListAssets:
    async def test_returns_asset_list_from_alpaca(self):
        assets = _load("alpaca_assets.json")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=assets)

        service = _make_service(handler)
        result = await service.list_assets()

        assert result == assets
        assert result[0]["symbol"] == "AAPL"

    async def test_sends_default_query_params(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        service = _make_service(handler)
        await service.list_assets()

        assert captured["method"] == "GET"
        assert captured["url"].split("?")[0].endswith("/v1/assets")
        assert captured["query"] == {
            "status": ["active"],
            "asset_class": ["us_equity"],
        }

    async def test_passes_explicit_query_params(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        service = _make_service(handler)
        await service.list_assets(status="inactive", asset_class="crypto")

        assert captured["query"] == {
            "status": ["inactive"],
            "asset_class": ["crypto"],
        }

    async def test_500_raises_alpaca_broker_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "internal server error"})

        service = _make_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.list_assets()

        assert info.value.status_code == 500
        assert "internal server error" in info.value.message

    async def test_connection_failure_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("connection timed out")

        service = _make_service(handler)
        with pytest.raises(AlpacaBrokerUnavailableError):
            await service.list_assets()
