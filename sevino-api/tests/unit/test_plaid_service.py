import json
from pathlib import Path
from unittest.mock import MagicMock

import plaid
import pytest

from app.services.plaid import PlaidService, PlaidServiceError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "mock_responses"


def _load(name: str) -> dict:
    with (FIXTURES / name).open() as f:
        return json.load(f)


def _mock_response(payload: dict) -> MagicMock:
    result = MagicMock()
    result.to_dict.return_value = payload
    return result


@pytest.fixture
def service() -> PlaidService:
    svc = PlaidService()
    svc._client = MagicMock()
    return svc


class TestCreateLinkToken:
    async def test_sends_expected_payload(self, service: PlaidService):
        service._client.link_token_create.return_value = _mock_response(
            _load("plaid_link_token.json")
        )

        await service.create_link_token(user_id="user-123")

        service._client.link_token_create.assert_called_once()
        (request,), _ = service._client.link_token_create.call_args
        body = request.to_dict()
        assert body["client_name"] == "Sevino"
        assert body["products"] == ["auth"]
        assert body["country_codes"] == ["US"]
        assert body["language"] == "en"
        assert body["user"]["client_user_id"] == "user-123"

    async def test_returns_link_token_from_response(self, service: PlaidService):
        fixture = _load("plaid_link_token.json")
        service._client.link_token_create.return_value = _mock_response(fixture)

        token = await service.create_link_token(user_id="user-123")

        assert token == fixture["link_token"]


class TestExchangePublicToken:
    async def test_sends_expected_payload(self, service: PlaidService):
        service._client.item_public_token_exchange.return_value = _mock_response(
            _load("plaid_exchange.json")
        )

        await service.exchange_public_token(public_token="public-sandbox-abc")

        (request,), _ = service._client.item_public_token_exchange.call_args
        assert request.to_dict()["public_token"] == "public-sandbox-abc"

    async def test_returns_access_token_and_item_id(self, service: PlaidService):
        fixture = _load("plaid_exchange.json")
        service._client.item_public_token_exchange.return_value = _mock_response(fixture)

        access_token, item_id = await service.exchange_public_token(
            public_token="public-sandbox-abc"
        )

        assert access_token == fixture["access_token"]
        assert item_id == fixture["item_id"]


class TestCreateProcessorToken:
    async def test_sends_alpaca_processor(self, service: PlaidService):
        service._client.processor_token_create.return_value = _mock_response(
            _load("plaid_processor_token.json")
        )

        await service.create_processor_token(
            access_token="access-sandbox-abc",
            account_id="acc-1",
        )

        (request,), _ = service._client.processor_token_create.call_args
        body = request.to_dict()
        assert body["processor"] == "alpaca"
        assert body["access_token"] == "access-sandbox-abc"
        assert body["account_id"] == "acc-1"

    async def test_returns_processor_token(self, service: PlaidService):
        fixture = _load("plaid_processor_token.json")
        service._client.processor_token_create.return_value = _mock_response(fixture)

        token = await service.create_processor_token(
            access_token="access-sandbox-abc",
            account_id="acc-1",
        )

        assert token == fixture["processor_token"]


class TestCreateUpdateLinkToken:
    async def test_sends_access_token_and_omits_products(
        self, service: PlaidService
    ):
        service._client.link_token_create.return_value = _mock_response(
            _load("plaid_link_token.json")
        )

        await service.create_update_link_token(
            user_id="user-123", access_token="access-sandbox-abc"
        )

        (request,), _ = service._client.link_token_create.call_args
        body = request.to_dict()
        assert body["access_token"] == "access-sandbox-abc"
        assert body["user"]["client_user_id"] == "user-123"
        assert body["client_name"] == "Sevino"
        assert body["country_codes"] == ["US"]
        assert body["language"] == "en"
        # Update mode forbids `products` per Plaid docs.
        assert "products" not in body

    async def test_returns_link_token_from_response(
        self, service: PlaidService
    ):
        fixture = _load("plaid_link_token.json")
        service._client.link_token_create.return_value = _mock_response(fixture)

        token = await service.create_update_link_token(
            user_id="user-123", access_token="access-sandbox-abc"
        )

        assert token == fixture["link_token"]


class TestGetWebhookVerificationKey:
    async def test_sends_key_id_in_request(self, service: PlaidService):
        service._client.webhook_verification_key_get.return_value = _mock_response(
            _load("plaid_webhook_key.json")
        )

        await service.get_webhook_verification_key("kid-abc-123")

        (request,), _ = service._client.webhook_verification_key_get.call_args
        assert request.to_dict()["key_id"] == "kid-abc-123"

    async def test_returns_only_the_key_field(self, service: PlaidService):
        fixture = _load("plaid_webhook_key.json")
        service._client.webhook_verification_key_get.return_value = _mock_response(
            fixture
        )

        key = await service.get_webhook_verification_key("kid-abc-123")

        assert key == fixture["key"]
        assert key["kid"] == "bfbd5111-8e33-4643-8ced-b2e642a72f3c"


class TestErrorMapping:
    async def test_plaid_api_exception_maps_to_service_error(self, service: PlaidService):
        body = json.dumps(
            {
                "error_code": "INVALID_CREDENTIALS",
                "error_message": "the provided credentials were not correct",
                "display_message": "The credentials provided were not correct.",
                "error_type": "ITEM_ERROR",
                "request_id": "abc123",
            }
        )
        exc = plaid.ApiException(status=400, reason="Bad Request")
        exc.body = body
        service._client.link_token_create.side_effect = exc

        with pytest.raises(PlaidServiceError) as info:
            await service.create_link_token(user_id="user-123")

        err = info.value
        assert err.code == "INVALID_CREDENTIALS"
        assert err.message == "The credentials provided were not correct."
        assert err.detail["status_code"] == 400
        assert err.detail["error_type"] == "ITEM_ERROR"
        assert err.detail["request_id"] == "abc123"

    async def test_plaid_exception_without_body_falls_back_to_reason(
        self, service: PlaidService
    ):
        exc = plaid.ApiException(status=500, reason="Internal Server Error")
        service._client.item_public_token_exchange.side_effect = exc

        with pytest.raises(PlaidServiceError) as info:
            await service.exchange_public_token(public_token="public-x")

        assert info.value.code == "PLAID_ERROR"
        assert info.value.message == "Internal Server Error"
        assert info.value.detail["status_code"] == 500


class TestInit:
    def test_rejects_unsupported_env(self, monkeypatch):
        from app.services import plaid as plaid_module

        monkeypatch.setattr(plaid_module.settings, "plaid_env", "development")
        with pytest.raises(ValueError, match="Unsupported PLAID_ENV"):
            PlaidService()
