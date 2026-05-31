import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.exceptions import MarketDataUnavailableError
from app.services.digest.moves import (
    HOLDING_MOVE_PCT,
    MoveData,
    RunScopedStockBarsProvider,
    detect_overnight_moves,
    is_meaningful_move,
)


NOW = datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc)  # 9:00am ET


class FakeAlpacaBars:
    def __init__(self, bars: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        self.bars = bars
        self.calls: list[tuple[str, str]] = []

    async def get_stock_bars(
        self, symbol: str, *, timeframe: str, **_: Any
    ) -> list[dict[str, Any]]:
        self.calls.append((symbol, timeframe))
        return self.bars.get((symbol, timeframe), [])


class FailingMarketData:
    def __init__(self, exc: Exception, *, fail_timeframe: str = "1Day") -> None:
        self.exc = exc
        self.fail_timeframe = fail_timeframe

    async def get_stock_bars(
        self, symbol: str, *, timeframe: str, **_: Any
    ) -> list[dict[str, Any]]:
        if timeframe == self.fail_timeframe:
            raise self.exc
        return [{"t": "2026-05-28T04:00:00Z", "c": "100"}]


def _daily(symbol: str, close: str) -> tuple[tuple[str, str], list[dict[str, Any]]]:
    return (
        (symbol, "1Day"),
        [{"t": "2026-05-28T04:00:00Z", "c": close}],
    )


def _minute(
    symbol: str, *closes: tuple[str, str]
) -> tuple[tuple[str, str], list[dict[str, Any]]]:
    return (
        (symbol, "1Min"),
        [{"t": timestamp, "c": close} for timestamp, close in closes],
    )


async def test_detect_overnight_moves_positive_move():
    alpaca = FakeAlpacaBars(
        dict(
            [
                _daily("AAPL", "100"),
                _minute(
                    "AAPL",
                    ("2026-05-29T12:00:00Z", "102"),
                    ("2026-05-29T12:59:00Z", "103"),
                ),
            ]
        )
    )

    moves = await detect_overnight_moves(["AAPL"], alpaca, now=NOW)

    move = moves["AAPL"]
    assert move == MoveData(
        prev_close=Decimal("100"),
        current=Decimal("103"),
        change_abs=Decimal("3"),
        change_pct=Decimal("0.03"),
        has_premarket_activity=True,
    )
    assert is_meaningful_move(move, HOLDING_MOVE_PCT) is True


async def test_detect_overnight_moves_negative_move():
    alpaca = FakeAlpacaBars(
        dict(
            [
                _daily("TSLA", "100"),
                _minute("TSLA", ("2026-05-29T12:59:00Z", "97.5")),
            ]
        )
    )

    moves = await detect_overnight_moves(["TSLA"], alpaca, now=NOW)

    move = moves["TSLA"]
    assert move.prev_close == Decimal("100")
    assert move.current == Decimal("97.5")
    assert move.change_abs == Decimal("-2.5")
    assert move.change_pct == Decimal("-0.025")
    assert move.has_premarket_activity is True
    assert is_meaningful_move(move, HOLDING_MOVE_PCT) is True


async def test_detect_overnight_moves_no_premarket_activity():
    alpaca = FakeAlpacaBars(dict([_daily("MSFT", "250.40")]))

    moves = await detect_overnight_moves(["MSFT"], alpaca, now=NOW)

    move = moves["MSFT"]
    assert move.prev_close == Decimal("250.40")
    assert move.current == Decimal("250.40")
    assert move.change_abs == Decimal("0")
    assert move.change_pct == Decimal("0")
    assert move.has_premarket_activity is False
    assert (
        is_meaningful_move(
            MoveData(
                prev_close=Decimal("100"),
                current=Decimal("103"),
                change_abs=Decimal("3"),
                change_pct=Decimal("0.03"),
                has_premarket_activity=False,
            ),
            HOLDING_MOVE_PCT,
        )
        is False
    )


async def test_detect_overnight_moves_symbol_not_found_returns_empty_move():
    alpaca = FakeAlpacaBars({})

    moves = await detect_overnight_moves(["missing"], alpaca, now=NOW)

    assert set(moves) == {"MISSING"}
    move = moves["MISSING"]
    assert move.prev_close == Decimal("0")
    assert move.current == Decimal("0")
    assert move.change_abs == Decimal("0")
    assert move.change_pct == Decimal("0")
    assert move.has_premarket_activity is False
    assert isinstance(move.prev_close, Decimal)
    assert isinstance(move.current, Decimal)
    assert isinstance(move.change_abs, Decimal)
    assert isinstance(move.change_pct, Decimal)


async def test_detect_overnight_moves_market_data_failure_captures_batch_sentry(
    monkeypatch,
):
    captured_tags: dict[str, str] = {}
    captured_context: dict[str, dict[str, Any]] = {}
    captured_message: dict[str, Any] = {}

    class _Scope:
        def set_tag(self, key: str, value: str) -> None:
            captured_tags[key] = value

        def set_context(self, key: str, value: dict[str, Any]) -> None:
            captured_context[key] = value

    class _ScopeCtx:
        def __enter__(self) -> _Scope:
            return _Scope()

        def __exit__(self, *args: Any) -> bool:
            return False

    def capture_message(message: str, level: str | None = None) -> None:
        captured_message["message"] = message
        captured_message["level"] = level

    monkeypatch.setattr(
        "app.services.digest.moves.sentry_sdk.new_scope",
        lambda: _ScopeCtx(),
    )
    monkeypatch.setattr(
        "app.services.digest.moves.sentry_sdk.capture_message",
        capture_message,
    )

    moves = await detect_overnight_moves(
        ["AAPL", "MSFT"],
        FailingMarketData(MarketDataUnavailableError("alpaca down")),
        now=NOW,
    )

    assert set(moves) == {"AAPL", "MSFT"}
    assert all(
        move == MoveData(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), False)
        for move in moves.values()
    )
    assert captured_message == {
        "message": "digest_move_detection_failures",
        "level": "warning",
    }
    assert captured_tags["digest_component"] == "move_detection"
    assert captured_tags["alert_type"] == "digest_move_detection_failures"
    assert captured_tags["symbol_count"] == "2"
    assert captured_tags["failure_count"] == "2"
    context = captured_context["digest_move_detection"]
    assert context["stage_counts"] == {"daily": 2}
    assert context["error_counts"] == {"MarketDataUnavailableError": 2}


async def test_detect_overnight_moves_programming_errors_propagate():
    with pytest.raises(TypeError):
        await detect_overnight_moves(
            ["AAPL"], FailingMarketData(TypeError("bad fake")), now=NOW
        )


async def test_run_scoped_stock_bars_provider_deduplicates_in_flight_calls():
    class SlowMarketData:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get_stock_bars(
            self,
            symbol: str,
            *,
            timeframe: str,
            **_: Any,
        ) -> list[dict[str, Any]]:
            self.calls.append(f"{symbol}:{timeframe}")
            await asyncio.sleep(0)
            return [{"t": "2026-05-28T04:00:00Z", "c": "100"}]

    inner = SlowMarketData()
    provider = RunScopedStockBarsProvider(inner)

    first, second = await asyncio.gather(
        provider.get_stock_bars(
            "aapl",
            timeframe="1Day",
            start=NOW,
            end=NOW,
            limit=10,
        ),
        provider.get_stock_bars(
            "AAPL",
            timeframe="1Day",
            start=NOW,
            end=NOW,
            limit=10,
        ),
    )

    assert first == second == [{"t": "2026-05-28T04:00:00Z", "c": "100"}]
    assert inner.calls == ["aapl:1Day"]
