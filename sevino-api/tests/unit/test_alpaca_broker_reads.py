from unittest.mock import AsyncMock

import pytest

from app.services.alpaca_broker import AlpacaBrokerService


@pytest.fixture
def service():
    svc = AlpacaBrokerService.__new__(AlpacaBrokerService)
    svc._request = AsyncMock()  # type: ignore[method-assign]
    return svc


async def test_get_trading_account_calls_expected_endpoint(service):
    service._request.return_value = {"equity": "1000.00", "cash": "500.00"}

    result = await service.get_trading_account("acc_abc")

    assert result == {"equity": "1000.00", "cash": "500.00"}
    service._request.assert_awaited_once_with(
        "GET",
        "/v1/trading/accounts/acc_abc/account",
    )


async def test_get_positions_calls_expected_endpoint(service):
    service._request.return_value = [{"symbol": "AAPL", "qty": "10"}]

    result = await service.get_positions("acc_abc")

    assert result == [{"symbol": "AAPL", "qty": "10"}]
    service._request.assert_awaited_once_with(
        "GET",
        "/v1/trading/accounts/acc_abc/positions",
    )


async def test_get_portfolio_history_passes_all_params(service):
    service._request.return_value = {"timestamp": [], "equity": []}

    await service.get_portfolio_history(
        "acc_abc", period="1M", timeframe="1D", start="2025-01-01"
    )

    service._request.assert_awaited_once_with(
        "GET",
        "/v1/trading/accounts/acc_abc/account/portfolio/history",
        params={"period": "1M", "timeframe": "1D", "start": "2025-01-01"},
    )


async def test_get_portfolio_history_omits_none_params(service):
    service._request.return_value = {}

    await service.get_portfolio_history("acc_abc", period="1M")

    service._request.assert_awaited_once_with(
        "GET",
        "/v1/trading/accounts/acc_abc/account/portfolio/history",
        params={"period": "1M"},
    )


async def test_get_portfolio_history_with_no_params(service):
    service._request.return_value = {}

    await service.get_portfolio_history("acc_abc")

    service._request.assert_awaited_once_with(
        "GET",
        "/v1/trading/accounts/acc_abc/account/portfolio/history",
        params={},
    )
