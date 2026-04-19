import httpx
import pytest

from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService


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
