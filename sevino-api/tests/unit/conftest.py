import time
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

import app.services.radar_job.candidate_sourcer as candidate_sourcer
from app.models.asset import Asset
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)


@pytest.fixture
def make_alpaca_service() -> Callable[[Callable[[httpx.Request], httpx.Response]], AlpacaBrokerService]:
    """Build an AlpacaBrokerService whose AsyncClient uses MockTransport with `handler`.

    Pre-seeds an access token so the OAuth2 path isn't exercised.
    """

    def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> AlpacaBrokerService:
        service = AlpacaBrokerService()
        service._access_token = "fake-access-token"
        service._token_expires_at = time.time() + 3600
        service._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=30.0
        )
        return service

    return _factory


@pytest.fixture
def radar_asset() -> Callable[..., Asset]:
    """Build a gated `Asset` carrying only the fields the sourcer reads."""

    def _make(
        symbol: str,
        *,
        sector: str | None = "Technology",
        market_cap: int | None = 10_000_000_000,
        name: str | None = None,
    ) -> Asset:
        return Asset(
            symbol=symbol,
            name=name or f"{symbol} Inc",
            sector=sector,
            market_cap=market_cap,
        )

    return _make


@pytest.fixture
def run_build_pool(monkeypatch) -> Callable[..., object]:
    """Drive `candidate_sourcer.build_pool` with the DB-backed deps mocked.

    Returns a namespace with the resulting `pool` plus the `alpaca` / `events`
    mocks so tests can assert which dependencies were (or weren't) called.
    """

    async def _run(
        gated: list[Asset],
        *,
        positions: list[dict] | None = None,
        owned_sectors: set[str] | None = None,
        existing_radar: set[str] | None = None,
        account_status: str = "ACTIVE",
        has_brokerage: bool = True,
        earnings: list[dict] | None = None,
        dividends: list[dict] | None = None,
        alpaca_unavailable: bool = False,
    ):
        brokerage = (
            SimpleNamespace(
                alpaca_account_id="acct-123", account_status=account_status
            )
            if has_brokerage
            else None
        )

        monkeypatch.setattr(
            candidate_sourcer.BrokerageAccountRepository,
            "get_by_user_id",
            AsyncMock(return_value=brokerage),
        )
        monkeypatch.setattr(
            candidate_sourcer.RadarItemRepository,
            "list_all_symbols",
            AsyncMock(return_value=set(existing_radar or set())),
        )
        monkeypatch.setattr(
            candidate_sourcer.AssetRepository,
            "sectors_for_symbols",
            AsyncMock(return_value=set(owned_sectors or set())),
        )

        alpaca = AsyncMock()
        if alpaca_unavailable:
            alpaca.list_positions = AsyncMock(
                side_effect=AlpacaBrokerUnavailableError()
            )
        else:
            alpaca.list_positions = AsyncMock(return_value=positions or [])

        events = AsyncMock()
        events.upcoming_earnings = AsyncMock(return_value=earnings or [])
        events.upcoming_dividends = AsyncMock(return_value=dividends or [])

        pool = await candidate_sourcer.build_pool(
            uuid4(), gated, AsyncMock(), alpaca, events
        )
        return SimpleNamespace(pool=pool, alpaca=alpaca, events=events)

    return _run
