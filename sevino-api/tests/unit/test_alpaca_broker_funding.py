import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"

ACCOUNT_ID = "9d587d7a-1b4c-4b3a-95bb-0e8e0d5e7777"
REL_ID = "794c3c51-d831-4e8c-a0e1-0bad1a9f0123"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


class TestCreateAchRelationship:
    async def test_posts_processor_token(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_load("alpaca_ach_relationship.json"))

        service = make_alpaca_service(handler)
        result = await service.create_ach_relationship(
            ACCOUNT_ID, processor_token="processor-sandbox-xyz"
        )

        assert captured["method"] == "POST"
        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/ach_relationships")
        assert captured["body"] == {"processor_token": "processor-sandbox-xyz"}
        assert result["id"] == REL_ID

    async def test_409_raises_alpaca_broker_error(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"message": "relationship already exists"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.create_ach_relationship(ACCOUNT_ID, processor_token="p")

        assert info.value.status_code == 409
        assert "already exists" in info.value.message


class TestListAchRelationships:
    async def test_gets_relationships(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json=[_load("alpaca_ach_relationship.json")])

        service = make_alpaca_service(handler)
        result = await service.list_ach_relationships(ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/ach_relationships")
        assert len(result) == 1
        assert result[0]["id"] == REL_ID


class TestDeleteAchRelationship:
    async def test_204_returns_cleanly(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(204)

        service = make_alpaca_service(handler)
        result = await service.delete_ach_relationship(ACCOUNT_ID, REL_ID)

        assert result is None
        assert captured["method"] == "DELETE"
        assert captured["url"].endswith(
            f"/v1/accounts/{ACCOUNT_ID}/ach_relationships/{REL_ID}"
        )

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.delete_ach_relationship(ACCOUNT_ID, REL_ID)


class TestCreateTransfer:
    async def test_body_includes_ach_and_immediate(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["url"] = str(request.url)
            return httpx.Response(200, json=_load("alpaca_transfer.json"))

        service = make_alpaca_service(handler)
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
    async def test_query_string_contains_filters(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[_load("alpaca_transfer.json")])

        service = make_alpaca_service(handler)
        await service.list_transfers(ACCOUNT_ID, direction="INCOMING", limit=25)

        assert captured["query"] == {"direction": ["INCOMING"], "limit": ["25"]}

    async def test_no_params_sends_no_query(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = urlparse(str(request.url)).query
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        await service.list_transfers(ACCOUNT_ID)

        assert captured["query"] == ""


class TestGetTradingAccount:
    async def test_gets_trading_account(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json={
                    "id": ACCOUNT_ID,
                    "equity": "10234.56",
                    "cash": "1234.56",
                    "buying_power": "2469.12",
                    "portfolio_value": "10234.56",
                },
            )

        service = make_alpaca_service(handler)
        result = await service.get_trading_account(ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/account"
        )
        assert result["equity"] == "10234.56"
        assert result["cash"] == "1234.56"

    async def test_404_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "account not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.get_trading_account(ACCOUNT_ID)


class TestListPositions:
    async def test_gets_positions(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json=[{"asset_id": "a1", "symbol": "AAPL", "qty": "5"}],
            )

        service = make_alpaca_service(handler)
        result = await service.list_positions(ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(
            f"/v1/trading/accounts/{ACCOUNT_ID}/positions"
        )
        assert result == [{"asset_id": "a1", "symbol": "AAPL", "qty": "5"}]

    async def test_empty_list(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        assert await service.list_positions(ACCOUNT_ID) == []


class TestListDocuments:
    async def test_returns_documents(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "doc-1",
                        "type": "account_statement",
                        "date": "2026-03-31",
                        "name": "March Statement",
                    }
                ],
            )

        service = make_alpaca_service(handler)
        result = await service.list_documents(ACCOUNT_ID)

        assert captured["method"] == "GET"
        assert captured["url"].endswith(f"/v1/accounts/{ACCOUNT_ID}/documents")
        assert len(result) == 1
        assert result[0]["id"] == "doc-1"

    async def test_applies_type_start_end_filters(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = parse_qs(urlparse(str(request.url)).query)
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        await service.list_documents(
            ACCOUNT_ID,
            document_type="account_statement",
            start="2026-01-01",
            end="2026-03-31",
        )

        assert captured["query"] == {
            "type": ["account_statement"],
            "start": ["2026-01-01"],
            "end": ["2026-03-31"],
        }

    async def test_omits_none_filters(self, make_alpaca_service):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = urlparse(str(request.url)).query
            return httpx.Response(200, json=[])

        service = make_alpaca_service(handler)
        await service.list_documents(ACCOUNT_ID)

        assert captured["query"] == ""


class TestStreamDocument:
    async def test_yields_body_chunks(self, make_alpaca_service):
        captured: dict = {}
        pdf_bytes = b"%PDF-1.4\nfake"

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, content=pdf_bytes)

        service = make_alpaca_service(handler)
        iterator = await service.stream_document(ACCOUNT_ID, "doc-1")
        chunks = [c async for c in iterator]

        assert captured["method"] == "GET"
        assert captured["url"].endswith(
            f"/v1/accounts/{ACCOUNT_ID}/documents/doc-1/download"
        )
        assert b"".join(chunks) == pdf_bytes

    async def test_follows_redirect_to_s3(self, make_alpaca_service):
        pdf_bytes = b"%PDF-1.4\nfollowed"

        def handler(request: httpx.Request) -> httpx.Response:
            if "documents/doc-1/download" in str(request.url):
                return httpx.Response(
                    301, headers={"location": "https://s3.example/file.pdf"}
                )
            return httpx.Response(200, content=pdf_bytes)

        service = make_alpaca_service(handler)
        iterator = await service.stream_document(ACCOUNT_ID, "doc-1")
        chunks = [c async for c in iterator]

        assert b"".join(chunks) == pdf_bytes

    async def test_404_raises_not_found_before_iteration(self, make_alpaca_service):
        """A 404 must raise eagerly from `await stream_document(...)` so the
        route can return a proper 404 status, not a truncated 200 stream."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "document not found"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.stream_document(ACCOUNT_ID, "doc-1")


class TestErrorMapping:
    async def test_404_from_list_raises_not_found(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "account missing"})

        service = make_alpaca_service(handler)
        with pytest.raises(NotFoundError):
            await service.list_ach_relationships(ACCOUNT_ID)

    async def test_422_from_create_transfer_raises(self, make_alpaca_service):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "amount below minimum"})

        service = make_alpaca_service(handler)
        with pytest.raises(AlpacaBrokerError) as info:
            await service.create_transfer(
                ACCOUNT_ID,
                relationship_id=REL_ID,
                amount="0.50",
                direction="INCOMING",
            )

        assert info.value.status_code == 422
        assert "amount below minimum" in info.value.message
