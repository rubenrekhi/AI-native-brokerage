"""Unit tests for the `market_state` shortcut rule."""

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.shortcuts import Shortcut
from app.services.market_data import MarketDataError, MarketDataUnavailableError
from app.services.shortcuts import ranker
from app.services.shortcuts.context import ShortcutContext
from app.services.shortcuts.rules import market_state
from app.services.shortcuts.time_buckets import TimeBucket

USER = uuid.UUID("44444444-4444-4444-4444-444444444444")


def _ctx(bucket: TimeBucket) -> ShortcutContext:
    return ShortcutContext(
        user_id=USER,
        bucket=bucket,
        day=date(2026, 5, 30),
        account_age_days=100,
        conversation_count=100,
    )


def _md(quotes: dict[str, str]) -> AsyncMock:
    """Fake MarketDataService whose batch quotes carry the given percents."""
    md = AsyncMock()
    md.get_batch_quotes.return_value = {
        "quotes": [
            {"symbol": symbol, "change_percent": pct}
            for symbol, pct in quotes.items()
        ]
    }
    return md


def _db_with_sector_names(sectors: list[str]) -> AsyncMock:
    db = AsyncMock()
    result = Mock()
    result.scalars.return_value = Mock(all=Mock(return_value=sectors))
    db.execute.return_value = result
    return db


def _db_with_radar_count(count: int) -> AsyncMock:
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one=Mock(return_value=count))
    return db


def _patch_account(monkeypatch, status: str = "ACTIVE") -> None:
    monkeypatch.setattr(
        market_state.BrokerageAccountRepository,
        "get_by_user_id",
        AsyncMock(
            return_value=SimpleNamespace(
                alpaca_account_id="acct-1", account_status=status
            )
        ),
    )


class TestBigMove:
    async def test_fires_at_exactly_2_percent(self):
        md = _md({"SPY": "2.0"})
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert len(out) == 1
        assert out[0].text == "Why is the market up today?"
        assert out[0].category == "market_state"
        assert out[0].magnitude == pytest.approx(0.02)

    async def test_silent_at_1_99_percent(self):
        md = _md({"SPY": "1.99"})
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert out == []

    async def test_down_direction_and_magnitude(self):
        md = _md({"SPY": "-2.3"})
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert out[0].text == "Why is the market down today?"
        assert out[0].magnitude == pytest.approx(0.023)

    async def test_fires_after_market(self):
        md = _md({"SPY": "2.5"})
        out = await market_state._big_move(_ctx(TimeBucket.AFTER_MARKET), md)
        assert len(out) == 1

    async def test_silent_at_night(self):
        md = _md({"SPY": "5.0"})
        out = await market_state._big_move(_ctx(TimeBucket.NIGHT), md)
        assert out == []
        md.get_batch_quotes.assert_not_called()

    async def test_silent_in_morning(self):
        md = _md({"SPY": "5.0"})
        out = await market_state._big_move(_ctx(TimeBucket.MORNING), md)
        assert out == []
        md.get_batch_quotes.assert_not_called()

    async def test_silent_without_market_data(self):
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), None)
        assert out == []

    async def test_graceful_when_market_data_unavailable(self):
        md = AsyncMock()
        md.get_batch_quotes.side_effect = MarketDataUnavailableError()
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert out == []

    async def test_graceful_when_market_data_has_no_data(self):
        md = AsyncMock()
        md.get_batch_quotes.side_effect = MarketDataError("no data", symbol="SPY")
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert out == []

    async def test_silent_when_spy_quote_absent(self):
        md = _md({"QQQ": "5.0"})
        out = await market_state._big_move(_ctx(TimeBucket.MARKET_HOURS), md)
        assert out == []


class TestSectorLeadLag:
    async def test_fires_for_leading_sector(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "AAPL"}]
        db = _db_with_sector_names(["Technology"])
        md = _md({"SPY": "1.0", "XLK": "2.8"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        assert len(out) == 1
        assert out[0].text == "Why is Technology leading today?"
        assert out[0].category == "market_state"
        assert out[0].magnitude == pytest.approx(0.018)

    async def test_fires_for_lagging_sector(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "XOM"}]
        db = _db_with_sector_names(["Energy"])
        md = _md({"SPY": "1.0", "XLE": "-1.0"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        assert out[0].text == "Why is Energy lagging today?"
        assert out[0].magnitude == pytest.approx(0.02)

    async def test_emits_one_shortcut_per_affected_sector(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [
            {"symbol": "AAPL"},
            {"symbol": "XOM"},
        ]
        db = _db_with_sector_names(["Technology", "Energy"])
        md = _md({"SPY": "0.0", "XLK": "2.0", "XLE": "-1.6"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        texts = {s.text for s in out}
        assert texts == {
            "Why is Technology leading today?",
            "Why is Energy lagging today?",
        }

    async def test_silent_without_held_sectors(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "AAPL"}]
        db = _db_with_sector_names([])
        md = _md({"SPY": "1.0"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        assert out == []
        md.get_batch_quotes.assert_not_called()

    async def test_silent_below_spread_threshold(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "AAPL"}]
        db = _db_with_sector_names(["Technology"])
        md = _md({"SPY": "0.0", "XLK": "1.49"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        assert out == []

    async def test_silent_outside_market_hours(self, monkeypatch):
        alpaca = AsyncMock()
        md = _md({"SPY": "1.0", "XLK": "3.0"})
        for bucket in (
            TimeBucket.MORNING,
            TimeBucket.AFTER_MARKET,
            TimeBucket.NIGHT,
        ):
            out = await market_state._sector_lead_lag(
                _ctx(bucket), AsyncMock(), alpaca, md
            )
            assert out == []
        alpaca.list_positions.assert_not_called()

    async def test_silent_without_alpaca(self):
        md = _md({"SPY": "1.0", "XLK": "3.0"})
        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), AsyncMock(), None, md
        )
        assert out == []
        md.get_batch_quotes.assert_not_called()

    async def test_silent_when_spy_quote_absent(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "AAPL"}]
        db = _db_with_sector_names(["Technology"])
        md = _md({"XLK": "5.0"})

        out = await market_state._sector_lead_lag(
            _ctx(TimeBucket.MARKET_HOURS), db, alpaca, md
        )

        assert out == []


class TestMorningWatch:
    async def test_fires_with_positions(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = [{"symbol": "AAPL"}]
        db = AsyncMock()

        out = await market_state._morning_watch(
            _ctx(TimeBucket.MORNING), db, alpaca
        )

        assert len(out) == 1
        assert out[0].text == "Anything I should watch today?"
        assert out[0].category == "market_state"
        assert out[0].magnitude == pytest.approx(0.0)
        # Positions present short-circuits the radar count query.
        db.execute.assert_not_called()

    async def test_fires_with_radar_item_and_no_positions(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = []
        db = _db_with_radar_count(1)

        out = await market_state._morning_watch(
            _ctx(TimeBucket.MORNING), db, alpaca
        )

        assert len(out) == 1

    async def test_silent_without_positions_or_radar(self, monkeypatch):
        _patch_account(monkeypatch)
        alpaca = AsyncMock()
        alpaca.list_positions.return_value = []
        db = _db_with_radar_count(0)

        out = await market_state._morning_watch(
            _ctx(TimeBucket.MORNING), db, alpaca
        )

        assert out == []

    async def test_silent_outside_morning(self, monkeypatch):
        alpaca = AsyncMock()
        for bucket in (
            TimeBucket.MARKET_HOURS,
            TimeBucket.AFTER_MARKET,
            TimeBucket.NIGHT,
        ):
            out = await market_state._morning_watch(
                _ctx(bucket), AsyncMock(), alpaca
            )
            assert out == []
        alpaca.list_positions.assert_not_called()


class TestEvaluate:
    async def test_returns_empty_at_night(self):
        md = _md({"SPY": "5.0"})
        out = await market_state.evaluate(
            _ctx(TimeBucket.NIGHT), AsyncMock(), AsyncMock(), md
        )
        assert out == []
        md.get_batch_quotes.assert_not_called()

    async def test_big_move_ranks_above_quiet_state(self, monkeypatch):
        _patch_account(monkeypatch, status="SUBMITTED")
        md = _md({"SPY": "-2.3"})

        market = await market_state.evaluate(
            _ctx(TimeBucket.MARKET_HOURS), AsyncMock(), AsyncMock(), md
        )

        ranked = ranker.rank(
            {
                "first_time": [],
                "portfolio_state": [],
                "market_state": market,
                "quiet_state": [
                    Shortcut.create(text="filler", category="quiet_state")
                ],
            }
        )
        assert ranked[0].text == "Why is the market down today?"
