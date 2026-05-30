"""Unit tests for the `portfolio_state` shortcut rule."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.shortcuts import Shortcut
from app.services.alpaca_broker import AlpacaBrokerUnavailableError
from app.services.shortcuts import ranker
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import portfolio_state
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _snap(
    *,
    total: str,
    cash: str = "0",
    positions: list[tuple[str, str, str | None]] | None = None,
) -> portfolio_state._PortfolioSnapshot:
    return portfolio_state._PortfolioSnapshot(
        total_value=Decimal(total),
        cash=Decimal(cash),
        positions=[
            portfolio_state._Position(
                symbol=symbol, market_value=Decimal(mv), sector=sector
            )
            for symbol, mv, sector in (positions or [])
        ],
    )


def _ctx(
    bucket: TimeBucket = TimeBucket.MARKET_HOURS,
    day: date = date(2026, 5, 30),
) -> ShortcutContext:
    return ShortcutContext(
        user_id=USER,
        bucket=bucket,
        day=day,
        account_age_days=100,
        conversation_count=100,
    )


class TestConcentration:
    def test_fires_just_over_25_percent(self):
        snap = _snap(total="1000", positions=[("NVDA", "250.01", None)])
        out = portfolio_state._concentration(snap)
        assert len(out) == 1
        assert out[0].text == "Is having 25% in NVDA too much?"
        assert out[0].category == "portfolio_state"

    def test_silent_at_24_99_percent(self):
        snap = _snap(total="1000", positions=[("NVDA", "249.90", None)])
        assert portfolio_state._concentration(snap) == []

    def test_silent_below_portfolio_floor(self):
        # 100% concentration, but the whole portfolio is only $400.
        snap = _snap(total="400", positions=[("NVDA", "400", None)])
        assert portfolio_state._concentration(snap) == []

    def test_silent_at_exactly_floor(self):
        snap = _snap(total="500", positions=[("NVDA", "500", None)])
        assert portfolio_state._concentration(snap) == []

    def test_percent_rounds_for_display(self):
        snap = _snap(total="14000", positions=[("NVDA", "4480", None)])
        out = portfolio_state._concentration(snap)
        assert out[0].text == "Is having 32% in NVDA too much?"

    def test_magnitude_orders_heavier_position_first(self):
        snap = _snap(
            total="1000",
            positions=[("AAA", "350", None), ("BBB", "280", None)],
        )
        out = portfolio_state._concentration(snap)
        assert len(out) == 2
        heavy = next(s for s in out if "AAA" in s.text)
        light = next(s for s in out if "BBB" in s.text)
        assert heavy.magnitude == pytest.approx(0.35)
        assert light.magnitude == pytest.approx(0.28)
        assert heavy.magnitude > light.magnitude


class TestAllocationDrift:
    def test_fires_when_sector_over_40_percent(self):
        snap = _snap(
            total="1000",
            positions=[
                ("AAPL", "300", "Technology"),
                ("MSFT", "200", "Technology"),
                ("XOM", "100", "Energy"),
            ],
        )
        out = portfolio_state._allocation_drift(snap)
        assert len(out) == 1
        assert out[0].text == "Why is my Technology allocation so high?"
        assert out[0].magnitude == pytest.approx(0.50)

    def test_silent_when_sector_mapping_missing(self):
        snap = _snap(total="1000", positions=[("AAA", "600", None)])
        assert portfolio_state._allocation_drift(snap) == []

    def test_silent_below_portfolio_floor(self):
        snap = _snap(total="400", positions=[("AAPL", "400", "Technology")])
        assert portfolio_state._allocation_drift(snap) == []

    def test_silent_at_exactly_40_percent(self):
        snap = _snap(
            total="1000",
            positions=[
                ("AAPL", "400", "Technology"),
                ("XOM", "300", "Energy"),
                ("JNJ", "300", "Healthcare"),
            ],
        )
        assert portfolio_state._allocation_drift(snap) == []


class TestIdleCash:
    def test_fires_when_both_conditions_met(self):
        snap = _snap(total="14000", cash="5000")
        out = portfolio_state._idle_cash(snap)
        assert len(out) == 1
        assert out[0].text == (
            "What should I do with my cash sitting in the account?"
        )
        assert out[0].magnitude == pytest.approx(5000 / 14000)

    def test_silent_when_cash_below_floor(self):
        # 20% of the portfolio, but under the $500 absolute floor.
        snap = _snap(total="2000", cash="400")
        assert portfolio_state._idle_cash(snap) == []

    def test_silent_when_ratio_too_low(self):
        # Over $500, but a rounding-error slice of a large portfolio.
        snap = _snap(total="100000", cash="600")
        assert portfolio_state._idle_cash(snap) == []


class TestDailyRecap:
    def test_fires_only_in_after_market(self):
        snap = _snap(total="1000", positions=[("AAPL", "100", None)])
        assert portfolio_state._daily_recap(snap, TimeBucket.AFTER_MARKET)
        for bucket in (
            TimeBucket.MORNING,
            TimeBucket.MARKET_HOURS,
            TimeBucket.NIGHT,
        ):
            assert portfolio_state._daily_recap(snap, bucket) == []

    def test_silent_without_positions(self):
        snap = _snap(total="1000", positions=[])
        assert portfolio_state._daily_recap(snap, TimeBucket.AFTER_MARKET) == []

    def test_recap_sorts_behind_sharper_signals(self):
        snap = _snap(total="1000", positions=[("NVDA", "400", None)])
        recap = portfolio_state._daily_recap(snap, TimeBucket.AFTER_MARKET)
        assert recap[0].magnitude == pytest.approx(0.0)
        ranked = ranker.rank(
            {
                "first_time": [],
                "portfolio_state": portfolio_state._concentration(snap) + recap,
                "quiet_state": [],
            }
        )
        assert ranked[0].text == "Is having 40% in NVDA too much?"
        assert ranked[-1].text == "How did my portfolio do today?"


def test_ranker_orders_portfolio_state_by_magnitude():
    snap = _snap(
        total="1000",
        positions=[("AAA", "350", None), ("BBB", "280", None)],
    )
    items = portfolio_state._concentration(snap)
    ranked = ranker.rank(
        {"first_time": [], "portfolio_state": items, "quiet_state": []}
    )
    assert ranked[0].text == "Is having 35% in AAA too much?"
    assert ranked[1].text == "Is having 28% in BBB too much?"


def test_magnitude_excluded_from_wire():
    shortcut = Shortcut.create(
        text="x", category="portfolio_state", magnitude=5.0
    )
    assert "magnitude" not in shortcut.model_dump(mode="json")


def _account(status: str = "ACTIVE") -> SimpleNamespace:
    return SimpleNamespace(alpaca_account_id="acct-1", account_status=status)


def _db_with_sectors(
    sectors: list[tuple[str, str]],
) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = Mock(all=Mock(return_value=sectors))
    return db


async def test_evaluate_returns_empty_without_alpaca():
    out = await portfolio_state.evaluate(_ctx(), AsyncMock(), alpaca=None)
    assert out == []


async def test_evaluate_returns_empty_when_account_inactive(monkeypatch):
    monkeypatch.setattr(
        portfolio_state.BrokerageAccountRepository,
        "get_by_user_id",
        AsyncMock(return_value=_account("SUBMITTED")),
    )
    alpaca = AsyncMock()
    out = await portfolio_state.evaluate(_ctx(), AsyncMock(), alpaca)
    assert out == []
    alpaca.list_positions.assert_not_called()


async def test_evaluate_graceful_when_alpaca_unavailable(monkeypatch):
    monkeypatch.setattr(
        portfolio_state.BrokerageAccountRepository,
        "get_by_user_id",
        AsyncMock(return_value=_account()),
    )
    alpaca = AsyncMock()
    alpaca.get_trading_account.side_effect = AlpacaBrokerUnavailableError()
    alpaca.list_positions.return_value = []
    out = await portfolio_state.evaluate(_ctx(), AsyncMock(), alpaca)
    assert out == []


async def test_evaluate_surfaces_concentration_drift_and_idle_cash(monkeypatch):
    monkeypatch.setattr(
        portfolio_state.BrokerageAccountRepository,
        "get_by_user_id",
        AsyncMock(return_value=_account()),
    )
    alpaca = AsyncMock()
    alpaca.get_trading_account.return_value = {"equity": "14000", "cash": "5000"}
    alpaca.list_positions.return_value = [
        {"symbol": "NVDA", "market_value": "4480"},
        {"symbol": "MSFT", "market_value": "4520"},
    ]
    db = _db_with_sectors([("NVDA", "Technology"), ("MSFT", "Technology")])

    out = await portfolio_state.evaluate(_ctx(TimeBucket.MARKET_HOURS), db, alpaca)

    texts = {s.text for s in out}
    assert "Is having 32% in NVDA too much?" in texts
    assert "Why is my Technology allocation so high?" in texts
    assert "What should I do with my cash sitting in the account?" in texts
    assert all(s.category == "portfolio_state" for s in out)


async def test_evaluate_adds_daily_recap_after_market(monkeypatch):
    monkeypatch.setattr(
        portfolio_state.BrokerageAccountRepository,
        "get_by_user_id",
        AsyncMock(return_value=_account()),
    )
    alpaca = AsyncMock()
    alpaca.get_trading_account.return_value = {"equity": "1000", "cash": "0"}
    alpaca.list_positions.return_value = [
        {"symbol": "AAPL", "market_value": "100"},
    ]
    db = _db_with_sectors([])

    out = await portfolio_state.evaluate(_ctx(TimeBucket.AFTER_MARKET), db, alpaca)

    assert "How did my portfolio do today?" in {s.text for s in out}
