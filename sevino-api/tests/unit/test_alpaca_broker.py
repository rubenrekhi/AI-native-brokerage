import httpx
import pytest

from app.exceptions import NotFoundError
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)


def _response(status_code: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body or {},
        request=httpx.Request(
            "GET", "https://broker-api.sandbox.alpaca.markets/v1/accounts/xyz"
        ),
    )


def _service() -> AlpacaBrokerService:
    # Bypass __init__ — _handle_response doesn't touch instance state, and we
    # want to avoid settings reads and httpx.AsyncClient creation.
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


def test_handle_response_raises_not_found_with_resource_on_404():
    service = _service()
    response = _response(404, {"message": "account not found"})

    with pytest.raises(NotFoundError) as exc_info:
        service._handle_response(response)

    assert exc_info.value.resource == "alpaca_account"
    assert "account not found" in exc_info.value.message


async def test_close_account_posts_to_actions_close_endpoint(mocker):
    service = _service()
    request_mock = mocker.patch.object(
        AlpacaBrokerService,
        "_request",
        autospec=True,
        return_value={"status": "ACCOUNT_CLOSED"},
    )

    result = await service.close_account("alpaca_acc_42")

    assert result == {"status": "ACCOUNT_CLOSED"}
    request_mock.assert_awaited_once_with(
        service, "POST", "/v1/accounts/alpaca_acc_42/actions/close"
    )


async def test_list_orders_drops_none_params(mocker):
    service = _service()
    request_mock = mocker.patch.object(
        AlpacaBrokerService, "_request", autospec=True, return_value=[]
    )

    await service.list_orders("alpaca_acc_42", status="all", limit=50, direction="desc")

    request_mock.assert_awaited_once_with(
        service,
        "GET",
        "/v1/trading/accounts/alpaca_acc_42/orders",
        params={"status": "all", "limit": 50, "direction": "desc"},
    )


async def test_list_orders_no_params_passes_none(mocker):
    service = _service()
    request_mock = mocker.patch.object(
        AlpacaBrokerService, "_request", autospec=True, return_value=[]
    )

    await service.list_orders("alpaca_acc_42")

    request_mock.assert_awaited_once_with(
        service,
        "GET",
        "/v1/trading/accounts/alpaca_acc_42/orders",
        params=None,
    )


async def test_get_token_transport_error_raises_unavailable():
    service = _service()
    service._client_id = "id"
    service._client_secret = "secret"
    service._auth_url = "https://authx.sandbox.alpaca.markets"
    service._access_token = None
    service._token_expires_at = 0.0

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("token endpoint refused")

    service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(AlpacaBrokerUnavailableError):
        await service._get_token()


async def test_access_token_is_thin_alias_for_get_token(mocker):
    service = _service()
    get_token = mocker.patch.object(
        AlpacaBrokerService,
        "_get_token",
        autospec=True,
        return_value="tok-xyz",
    )

    result = await service.access_token()

    assert result == "tok-xyz"
    get_token.assert_awaited_once_with(service)
