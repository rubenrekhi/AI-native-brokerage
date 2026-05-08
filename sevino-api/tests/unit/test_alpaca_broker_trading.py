import json

import httpx
import pytest

from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerError

ACCOUNT_ID = "9d587d7a-1b4c-4b3a-95bb-0e8e0d5e7777"
ORDER_ID = "61e69015-8549-4bfd-b9c3-01e75843f47d"
SYMBOL = "AAPL"


class TestCreateOrder:
    async def test_posts_payload(self, make_alpaca_service):
        captured: dict = {}
        order_response = {
            "id": ORDER_ID,
            "symbol": SYMBOL,
            "side": "buy",
            "type": "market",
            "status": "accepted",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=order_response)

        service = make_alpaca_service(handler)
        payload = {
            "symbol": SYMBOL,
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": "1",
        }
        result = await service.create_order(ACCOUNT_ID, payload)

        assert captured["method"] == "POST"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/orders"
        )
        assert captured["body"] == payload
        assert result == order_response

    async def test_422_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "insufficient buying power"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.create_order(
                ACCOUNT_ID,
                {
                    "symbol": SYMBOL,
                    "side": "buy",
                    "type": "market",
                    "time_in_force": "day",
                    "qty": "1",
                },
            )

        assert info.value.status_code == 422
        assert "insufficient buying power" in info.value.message


class TestGetOrder:
    async def test_gets_order(self, make_alpaca_service):
        captured: dict = {}
        order_response = {
            "id": ORDER_ID,
            "symbol": SYMBOL,
            "status": "filled",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json=order_response)

        service = make_alpaca_service(handler)
        result = await service.get_order(ACCOUNT_ID, ORDER_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/orders/{ORDER_ID}"
        )
        assert result == order_response

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "order not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.get_order(ACCOUNT_ID, ORDER_ID)


class TestCancelOrder:
    async def test_204_returns_none(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(204)

        service = make_alpaca_service(handler)
        result = await service.cancel_order(ACCOUNT_ID, ORDER_ID)

        assert result is None
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/orders/{ORDER_ID}"
        )

    async def test_422_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "order not cancelable"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.cancel_order(ACCOUNT_ID, ORDER_ID)

        assert info.value.status_code == 422
        assert "not cancelable" in info.value.message


class TestGetPosition:
    async def test_gets_position(self, make_alpaca_service):
        captured: dict = {}
        position_response = {
            "asset_id": "b0b71f47-6cdf-4a44-9bca-0b9a4a48cdde",
            "symbol": SYMBOL,
            "qty": "5",
            "market_value": "987.65",
            "current_price": "197.53",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json=position_response)

        service = make_alpaca_service(handler)
        result = await service.get_position(ACCOUNT_ID, SYMBOL)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/positions/{SYMBOL}"
        )
        assert result == position_response

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "position does not exist"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.get_position(ACCOUNT_ID, SYMBOL)
