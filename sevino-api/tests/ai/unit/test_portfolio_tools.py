"""Unit tests for ``app.ai.tools.portfolio``.

Covers both portfolio tools end to end at the tool boundary — the
``PortfolioService`` and the brokerage-account lookup are patched, so these
exercise payload shaping, the pill lifecycle, and every error branch the
agent loop must not crash on:

* ``get_portfolio`` overview — balances + holdings rollup, lean (no full list).
* ``get_portfolio`` positions — full per-position P/L + weight; truncation cap.
* ``get_portfolio`` symbols filter — selected only, with ``not_held``.
* ``get_portfolio_performance`` — gain stats, high/low, downsampled trend.
* Error paths — no/inactive account, missing deps, brokerage unavailable.
* Input validation — detail/range literals, symbol cap.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.blocks import StatusBlock
from app.ai.tools import ToolContext, ToolHttpClients
from app.ai.tools.portfolio import (
    GetPortfolio,
    GetPortfolioPerformance,
    PortfolioInput,
    PortfolioPerformanceInput,
)
from app.ai.transport.events import BlockData, BlockStart, Event
from app.schemas.portfolio import (
    HoldingsResponse,
    PortfolioHistoryPoint,
    PortfolioHistoryResponse,
    PortfolioSnapshotResponse,
    Position,
)
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)

_SENTINEL = object()


def _account(status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(account_status=status, alpaca_account_id="acct-1")


def _snapshot(
    *,
    equity: str = "18432.55",
    cash: str = "1204.10",
    buying_power: str = "2408.20",
    last_equity: str = "18220.15",
    daily_abs: str = "212.40",
    daily_pct: str = "0.0117",
    status: str = "ACTIVE",
) -> PortfolioSnapshotResponse:
    return PortfolioSnapshotResponse(
        account_status=status,
        currency="USD",
        equity=Decimal(equity),
        last_equity=Decimal(last_equity),
        cash=Decimal(cash),
        buying_power=Decimal(buying_power),
        daily_change_abs=Decimal(daily_abs),
        daily_change_pct=Decimal(daily_pct),
    )


def _position(
    symbol: str,
    *,
    name: str | None = None,
    qty: str = "10",
    market_value: str = "1000.00",
    avg_entry: str = "90.00",
    current_price: str = "100.00",
    cost_basis: str = "900.00",
    unrealized_pl: str = "100.00",
    unrealized_plpc: str = "0.1111",
    change_today: str = "5.00",
    change_today_percent: str = "0.0050",
) -> Position:
    return Position(
        symbol=symbol,
        name=name or symbol,
        qty=Decimal(qty),
        avg_entry_price=Decimal(avg_entry),
        current_price=Decimal(current_price),
        market_value=Decimal(market_value),
        cost_basis=Decimal(cost_basis),
        unrealized_pl=Decimal(unrealized_pl),
        unrealized_plpc=Decimal(unrealized_plpc),
        change_today=Decimal(change_today),
        change_today_percent=Decimal(change_today_percent),
    )


def _holdings(
    positions: list[Position],
    *,
    cash: str = "1204.10",
    buying_power: str = "2408.20",
    status: str = "ACTIVE",
) -> HoldingsResponse:
    # Mirror the service, which sorts positions by market value desc.
    ordered = sorted(positions, key=lambda p: p.market_value, reverse=True)
    total = sum((p.market_value for p in ordered), Decimal("0"))
    return HoldingsResponse(
        account_status=status,
        currency="USD",
        cash=Decimal(cash),
        buying_power=Decimal(buying_power),
        total_market_value=total,
        positions=ordered,
    )


def _history(
    points: list[tuple[str, str]],
    *,
    range_: str = "1Y",
    timeframe: str = "1D",
    base: str = "12000.00",
) -> PortfolioHistoryResponse:
    pts = [PortfolioHistoryPoint(t=t, v=Decimal(v)) for t, v in points]
    end = pts[-1].v if pts else Decimal("0")
    base_d = Decimal(base)
    gain_abs = end - base_d
    gain_pct = (gain_abs / base_d) if base_d != 0 else Decimal("0")
    return PortfolioHistoryResponse(
        range=range_,
        timeframe=timeframe,
        currency="USD",
        base_value=base_d,
        end_value=end,
        gain_abs=gain_abs,
        gain_pct=gain_pct,
        points=pts,
    )


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


@asynccontextmanager
async def _fake_db_factory():
    yield MagicMock()


def _make_ctx(
    *, alpaca: Any = _SENTINEL, redis: Any = _SENTINEL
) -> tuple[ToolContext, _RecordingEmitter]:
    emitter = _RecordingEmitter()
    ctx = ToolContext(
        user_id=uuid4(),
        db_factory=_fake_db_factory,
        sse_emitter=emitter,  # type: ignore[arg-type]
        http_clients=ToolHttpClients(
            alpaca=MagicMock() if alpaca is _SENTINEL else alpaca,
            redis=MagicMock() if redis is _SENTINEL else redis,
        ),
    )
    return ctx, emitter


def _service(
    *,
    snapshot: PortfolioSnapshotResponse | None = None,
    holdings: HoldingsResponse | None = None,
    history: PortfolioHistoryResponse | None = None,
    snapshot_exc: Exception | None = None,
    history_exc: Exception | None = None,
) -> MagicMock:
    svc = MagicMock()
    svc.get_snapshot = AsyncMock(return_value=snapshot, side_effect=snapshot_exc)
    svc.get_holdings = AsyncMock(return_value=holdings)
    svc.get_history = AsyncMock(return_value=history, side_effect=history_exc)
    return svc


def _patch(monkeypatch, *, account: Any, service: MagicMock) -> None:
    monkeypatch.setattr(
        "app.ai.tools.portfolio.BrokerageAccountRepository.get_by_user_id",
        AsyncMock(return_value=account),
    )
    monkeypatch.setattr(
        "app.ai.tools.portfolio.PortfolioService",
        MagicMock(return_value=service),
    )


class TestPortfolioOverview:
    async def test_returns_balances_and_holdings_rollup(self, monkeypatch):
        positions = [
            _position("NVDA", market_value="5120.00", change_today_percent="0.0240"),
            _position("AAPL", market_value="3010.50", change_today_percent="-0.0060"),
            _position("MSFT", market_value="2740.00"),
        ]
        svc = _service(snapshot=_snapshot(), holdings=_holdings(positions))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, emitter = _make_ctx()

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        p = result.model_payload
        assert p["equity"] == "18432.55"
        assert p["cash"] == "1204.10"
        assert p["buying_power"] == "2408.20"
        assert p["invested"] == "10870.50"
        assert p["day_change_pct"] == "0.0117"
        assert "as_of" in p
        # Overview is lean: the full per-position list is NOT included.
        assert "positions" not in p

        h = p["holdings"]
        assert h["count"] == 3
        assert [t["symbol"] for t in h["top"]] == ["NVDA", "AAPL", "MSFT"]
        assert h["top"][0]["weight"] == "0.4710"
        assert "100%" in h["concentration_note"]

        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.internal_trace is not None
        assert "snapshot" in result.internal_trace

    async def test_emits_active_then_complete_pill(self, monkeypatch):
        svc = _service(snapshot=_snapshot(), holdings=_holdings([_position("NVDA")]))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, emitter = _make_ctx()

        await GetPortfolio().execute(PortfolioInput(), ctx)

        assert len(emitter.events) == 2
        start, patch = emitter.events
        assert isinstance(start, BlockStart)
        assert start.block["state"] == "active"
        assert start.block["label"] == "Reading your portfolio"
        assert isinstance(patch, BlockData)
        assert patch.block_id == start.block["block_id"]
        assert patch.data["state"] == "complete"

    async def test_all_cash_portfolio_notes_no_positions(self, monkeypatch):
        svc = _service(snapshot=_snapshot(), holdings=_holdings([]))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        h = result.model_payload["holdings"]
        assert h["count"] == 0
        assert h["top"] == []
        assert "cash" in h["concentration_note"].lower()


class TestPortfolioPositions:
    async def test_positions_detail_includes_pl_and_weight(self, monkeypatch):
        positions = [
            _position(
                "NVDA",
                market_value="5120.00",
                unrealized_pl="1312.00",
                unrealized_plpc="0.3446",
                change_today="120.00",
            )
        ]
        svc = _service(snapshot=_snapshot(), holdings=_holdings(positions))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(
            PortfolioInput(detail="positions"), ctx
        )

        p = result.model_payload
        assert p["count"] == 1
        assert "holdings" not in p
        pos = p["positions"][0]
        assert pos["symbol"] == "NVDA"
        assert pos["unrealized_pl"] == "1312.00"
        assert pos["unrealized_pl_pct"] == "0.3446"
        assert pos["day_change_abs"] == "120.00"
        assert pos["weight"] == "1.0000"
        assert "truncated" not in p

    async def test_positions_truncated_to_cap_with_more_notice(self, monkeypatch):
        positions = [
            _position(f"S{i:02d}", market_value=str(1000 - i)) for i in range(60)
        ]
        svc = _service(snapshot=_snapshot(), holdings=_holdings(positions))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(
            PortfolioInput(detail="positions"), ctx
        )

        p = result.model_payload
        assert len(p["positions"]) == 50
        assert p["count"] == 60
        assert p["truncated"] is True
        assert "60" in p["more"] and "50" in p["more"]
        # Sorted by value desc — the smallest 10 are the ones dropped.
        assert p["positions"][0]["symbol"] == "S00"

    async def test_symbols_filter_selects_and_reports_not_held(self, monkeypatch):
        positions = [
            _position("NVDA", market_value="5120.00"),
            _position("AAPL", market_value="3010.50"),
        ]
        svc = _service(snapshot=_snapshot(), holdings=_holdings(positions))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(
            PortfolioInput(symbols=["nvda", "tsla"]), ctx
        )

        p = result.model_payload
        assert [pos["symbol"] for pos in p["positions"]] == ["NVDA"]
        assert p["not_held"] == ["TSLA"]
        assert "holdings" not in p


class TestPortfolioErrors:
    async def test_inactive_account_returns_instructive_payload(self, monkeypatch):
        svc = _service(snapshot=_snapshot(), holdings=_holdings([]))
        _patch(monkeypatch, account=_account("SUBMITTED"), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        p = result.model_payload
        assert p["code"] == "ACCOUNT_NOT_ACTIVE"
        assert p["account_status"] == "SUBMITTED"
        assert result.ui_block is not None and result.ui_block.state == "failed"
        svc.get_snapshot.assert_not_awaited()

    async def test_missing_account_returns_instructive_payload(self, monkeypatch):
        _patch(monkeypatch, account=None, service=_service())
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        assert result.model_payload["code"] == "ACCOUNT_NOT_ACTIVE"
        assert result.model_payload["account_status"] is None

    async def test_missing_deps_returns_config_error(self, monkeypatch):
        ctx, emitter = _make_ctx(alpaca=None)

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        assert result.model_payload["code"] == "PORTFOLIO_UNAVAILABLE"
        assert result.ui_block is not None and result.ui_block.state == "failed"
        assert emitter.events[-1].data["state"] == "failed"

    @pytest.mark.parametrize(
        "exc",
        [
            AlpacaBrokerUnavailableError("down"),
            AlpacaBrokerError(503, "service unavailable"),
        ],
    )
    async def test_brokerage_error_returns_unavailable_payload(
        self, monkeypatch, exc
    ):
        svc = _service(
            snapshot_exc=exc, holdings=_holdings([_position("NVDA")])
        )
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolio().execute(PortfolioInput(), ctx)

        assert result.model_payload["code"] == "BROKERAGE_UNAVAILABLE"
        assert result.ui_block is not None and result.ui_block.state == "failed"


class TestPerformance:
    async def test_returns_gain_stats_and_high_low(self, monkeypatch):
        points = [
            ("2025-06-01T00:00:00Z", "12000.00"),
            ("2025-09-01T00:00:00Z", "11240.00"),
            ("2026-01-01T00:00:00Z", "15000.00"),
            ("2026-05-30T00:00:00Z", "18432.55"),
        ]
        svc = _service(history=_history(points, base="12000.00"))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(range="1Y"), ctx
        )

        p = result.model_payload
        assert p["range"] == "1Y"
        assert p["base_value"] == "12000.00"
        assert p["end_value"] == "18432.55"
        assert p["gain_abs"] == "6432.55"
        assert p["n_points"] == 4
        assert p["high"]["v"] == "18432.55"
        assert p["low"]["v"] == "11240.00"
        assert len(p["trend"]) == 4
        assert "as_of" in p
        assert result.ui_block is not None and result.ui_block.state == "complete"
        svc.get_history.assert_awaited_once()

    async def test_downsamples_to_trend_cap_keeping_endpoints(self, monkeypatch):
        points = [
            (f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", str(10000 + i))
            for i in range(100)
        ]
        svc = _service(history=_history(points, base="10000.00"))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(), ctx
        )

        p = result.model_payload
        assert p["n_points"] == 100
        assert len(p["trend"]) <= 16
        assert p["trend"][0]["v"] == "10000.00"
        assert p["trend"][-1]["v"] == "10099.00"

    async def test_empty_history_is_graceful(self, monkeypatch):
        svc = _service(history=_history([], base="0"))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(range="1D"), ctx
        )

        p = result.model_payload
        assert p["n_points"] == 0
        assert p["trend"] == []
        assert "high" not in p
        assert result.ui_block is not None and result.ui_block.state == "complete"

    async def test_inactive_account_returns_instructive_payload(self, monkeypatch):
        svc = _service(history=_history([]))
        _patch(monkeypatch, account=_account("PENDING"), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(), ctx
        )

        assert result.model_payload["code"] == "ACCOUNT_NOT_ACTIVE"
        svc.get_history.assert_not_awaited()

    async def test_brokerage_error_returns_unavailable_payload(self, monkeypatch):
        svc = _service(history_exc=AlpacaBrokerError(500, "boom"))
        _patch(monkeypatch, account=_account(), service=svc)
        ctx, _ = _make_ctx()

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(), ctx
        )

        assert result.model_payload["code"] == "BROKERAGE_UNAVAILABLE"

    async def test_missing_deps_returns_config_error(self, monkeypatch):
        ctx, _ = _make_ctx(redis=None)

        result = await GetPortfolioPerformance().execute(
            PortfolioPerformanceInput(), ctx
        )

        assert result.model_payload["code"] == "PORTFOLIO_UNAVAILABLE"


class TestInputValidation:
    def test_defaults(self):
        assert PortfolioInput().detail == "overview"
        assert PortfolioInput().symbols is None
        assert PortfolioPerformanceInput().range == "1M"

    def test_invalid_detail_rejected(self):
        with pytest.raises(ValidationError):
            PortfolioInput(detail="everything")

    def test_invalid_range_rejected(self):
        with pytest.raises(ValidationError):
            PortfolioPerformanceInput(range="2D")

    def test_too_many_symbols_rejected(self):
        with pytest.raises(ValidationError):
            PortfolioInput(symbols=[f"S{i}" for i in range(31)])
