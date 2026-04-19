import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.exceptions import NotFoundError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"

ACCOUNT_ID = "9d587d7a-1b4c-4b3a-95bb-0e8e0d5e7777"
REL_ID = "794c3c51-d831-4e8c-a0e1-0bad1a9f0123"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _make_service(handler) -> AlpacaBrokerService:
    """Build an AlpacaBrokerService whose AsyncClient uses MockTransport with `handler`.

    Pre-seeds an access token so the OAuth2 path isn't exercised.
    """
    service = AlpacaBrokerService()
    service._access_token = "fake-access-token"
    service._token_expires_at = time.time() + 3600
    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30.0)
    return service


class TestCreateAchRelationship:
    async def test_posts_processor_token(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_load("alpaca_ach_relationship.json"))

        service = _make_service(handler)
        result = await service.create_ach_relationship(
            ACCOUNT_ID, processor_token="processor-sandbox-xyz"
        )

        assert captured["method"] == "POST"
        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/ach_relationships")
        assert captured["body"] == {"processor_token": "processor-sandbox-xyz"}
        assert result["id"] == REL_ID

    async def test_409_raises_alpaca_broker_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"message": "relationship already exists"})

        service = _make_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.create_ach_relationship(ACCOUNT_ID, processor_token="p")

        assert info.value.status_code == 409
        assert "already exists" in info.value.message


class TestListAchRelationships:
    async def test_gets_relationships(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json=[_load("alpaca_ach_relationship.json")])

        service = _make_service(handler)
        result = await service.list_ach_relationships(ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/ach_relationships")
        assert len(result) == 1
        assert result[0]["id"] == REL_ID


class TestDeleteAchRelationship:
    async def test_204_returns_cleanly(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(204)

        service = _make_service(handler)
        result = await service.delete_ach_relationship(ACCOUNT_ID, REL_ID)

        assert result is None
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith(
            f"/v1/accounts/{ACCOUNT_ID}/ach_relationships/{REL_ID}"
        )

    async def test_404_raises_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        service = _make_service(handler)
        with pytest.raises(NotFoundError):
            await service.delete_ach_relationship(ACCOUNT_ID, REL_ID)


class TestCreateTransfer:
    async def test_body_includes_ach_and_immediate(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["url"] = str(request.url)
            return httpx.Response(200, json=_load("alpaca_transfer.json"))

        service = _make_service(handler)
        await service.create_transfer(
            ACCOUNT_ID,
            relationship_id=REL_ID,
            amount="500.00",
            direction="INCOMING",
        )

        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/transfers")
        assert captured["body"] == {
            "transfer_type": "ach",
            "timing": "immediate",
            "relationship_id": REL_ID,
            "amount": "500.00",
            "direction": "INCOMING",
        }


class TestListTransfers:
    async def test_query_string_contains_filters(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[_load("alpaca_transfer.json")])

        service = _make_service(handler)
        await service.list_transfers(ACCOUNT_ID, direction="INCOMING", limit=25)

        assert captured["query"] == {"direction": ["INCOMING"], "limit": ["25"]}

    async def test_no_params_sends_no_query(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = urlparse(str(request.url)).query
            return httpx.Response(200, json=[])

        service = _make_service(handler)
        await service.list_transfers(ACCOUNT_ID)

        assert captured["query"] == ""


class TestErrorMapping:
    async def test_404_from_list_raises_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "account missing"})

        service = _make_service(handler)
        with pytest.raises(NotFoundError):
            await service.list_ach_relationships(ACCOUNT_ID)

    async def test_422_from_create_transfer_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "amount below minimum"})

        service = _make_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.create_transfer(
                ACCOUNT_ID,
                relationship_id=REL_ID,
                amount="0.50",
                direction="INCOMING",
            )

        assert info.value.status_code == 422
        assert "amount below minimum" in info.value.message
