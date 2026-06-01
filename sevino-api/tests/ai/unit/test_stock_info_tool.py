"""Unit tests for ``app.ai.tools.stock_info`` (``get_stock_info`` tool).

Covers the happy path plus every error branch the tool must handle so the
agent loop never crashes on a stock lookup:

* Happy path — pill goes active → complete, payload + internal_trace populated.
* Unknown ticker — ``MarketDataError`` mapped to error payload, pill failed.
* Invalid input from upstream — ``MarketDataInvalidInputError`` mapped likewise.
* Provider down — ``MarketDataUnavailableError`` returns "temporarily unavailable".
* Upstream non-2xx — ``MarketDataUpstreamError`` same.
* Missing service — ``ctx.http_clients.market_data is None`` (no FMP_API_KEY).
* Tiering — ``detail`` tiers + ``sections`` override trim ``model_payload``;
  the internal trace keeps every section.
* Input validation — empty / oversize ticker, bad detail / section rejected.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.blocks import StatusBlock
from app.ai.tools import ToolContext, ToolHttpClients
from app.ai.tools.stock_info import GetStockInfo, StockInfoInput
from app.ai.transport.events import BlockData, BlockStart, Event
from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)


_SAMPLE_RESPONSE = {
    "quote": {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "price": "189.84",
        "change": "1.23",
        "change_percent": "0.65",
        "year_high": "199.62",
        "year_low": "164.08",
        "price_avg_50": "185.30",
        "price_avg_200": "178.45",
    },
    "profile": {
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
    },
    "ratios": {"dividend_yield": "0.0048", "roe": "1.6072"},
    "financials": {"revenue": "391035000000", "net_income": "99803000000"},
    "valuation": {"pe": "31.2", "pe_vs_sector": "0.18"},
    "earnings": {
        "next_period_end": "2026-07-31",
        "avg_post_earnings_move_pct": "0.034",
    },
    "sector_context": {"sector_vs_market_pct": "0.0042", "peer_count": 4},
    "analyst": {"target_consensus": "220.50", "strong_buy": 12},
}

# Ranges the tool fetches charts for, in the same order as
# ``PERFORMANCE_RANGES`` in ``_performance.py``.
_RANGES = ("1D", "1W", "1M", "3M", "6M", "1Y")


def _chart_for_range(range_label: str, *, n: int = 3) -> dict[str, Any]:
    """Build a per-range chart payload where the close prices encode
    the range slot — lets tests verify the tool routed each chart's
    bars into the right ``performance`` entry.
    """
    base = 100.0 + (_RANGES.index(range_label) * 10)
    return {
        "symbol": "AAPL",
        "timeframe": range_label,
        "bars": [
            {
                "timestamp": f"2026-04-29T13:{i:02d}:00Z",
                "open": str(base),
                "high": str(base + 1),
                "low": str(base - 1),
                "close": str(base + i),
                "volume": 1_000_000,
                "vwap": str(base),
                "trade_count": 100,
            }
            for i in range(n)
        ],
    }


class _RecordingEmitter:
    """Test double for ``SSEEmitter`` — appends every event to a list."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


def _make_ctx(
    *, market_data: Any | None
) -> tuple[ToolContext, _RecordingEmitter]:
    emitter = _RecordingEmitter()
    ctx = ToolContext(
        user_id=uuid4(),
        db_factory=MagicMock(),
        sse_emitter=emitter,  # type: ignore[arg-type]
        http_clients=ToolHttpClients(market_data=market_data),
    )
    return ctx, emitter


def _market_data_mock(
    *,
    info: dict[str, Any] | None = None,
    info_exc: Exception | None = None,
    chart_exc_per_range: dict[str, Exception] | None = None,
) -> MagicMock:
    """Compose a ``MarketDataService`` mock with happy-path defaults.

    ``get_chart`` differentiates by range so tests can verify the tool
    routed each range's bars into the right performance entry.
    Per-range failures can be injected via ``chart_exc_per_range``.
    """
    md = MagicMock()
    if info_exc is not None:
        md.get_stock_info = AsyncMock(side_effect=info_exc)
    else:
        md.get_stock_info = AsyncMock(return_value=info or _SAMPLE_RESPONSE)

    chart_exc_per_range = chart_exc_per_range or {}

    async def _get_chart(symbol: str, range_label: str) -> dict[str, Any]:
        if range_label in chart_exc_per_range:
            raise chart_exc_per_range[range_label]
        return _chart_for_range(range_label)

    md.get_chart = AsyncMock(side_effect=_get_chart)
    return md


class TestHappyPath:
    async def test_returns_aggregated_payload_and_completes_pill(self):
        md = _market_data_mock()
        ctx, emitter = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="aapl"), ctx
        )

        md.get_stock_info.assert_awaited_once_with("AAPL")
        # Charts fetched once per range so per-range performance can
        # be computed via the shared helper.
        assert md.get_chart.await_count == len(_RANGES)
        chart_calls = {call.args for call in md.get_chart.await_args_list}
        assert chart_calls == {("AAPL", r) for r in _RANGES}

        # Default tier is "snapshot" → quote + performance only; the heavier
        # sections are trimmed from model_payload (but kept in the trace).
        assert result.model_payload["quote"] == _SAMPLE_RESPONSE["quote"]
        assert "performance" in result.model_payload
        assert set(result.model_payload) == {"quote", "performance"}

        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == "Pulling data on AAPL"

    async def test_emits_block_start_active_then_block_data_complete(self):
        md = _market_data_mock()
        ctx, emitter = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        assert len(emitter.events) == 2
        start, patch = emitter.events
        assert isinstance(start, BlockStart)
        assert start.block["type"] == "status"
        assert start.block["state"] == "active"
        assert start.block["label"] == "Pulling data on AAPL"

        assert isinstance(patch, BlockData)
        assert patch.block_id == start.block["block_id"]
        assert patch.data["state"] == "complete"
        assert patch.data["label"] == "Pulling data on AAPL"

        # The completed StatusBlock returned in ``ui_block`` shares the
        # block_id of the active one — the loop emits ``block_end`` for it.
        assert result.ui_block is not None
        assert result.ui_block.block_id == start.block["block_id"]

    async def test_ticker_is_normalised_to_uppercase_in_label(self):
        md = _market_data_mock()
        ctx, emitter = _make_ctx(market_data=md)

        await GetStockInfo().execute(StockInfoInput(ticker="msft"), ctx)

        assert emitter.events[0].block["label"] == "Pulling data on MSFT"
        md.get_stock_info.assert_awaited_once_with("MSFT")

    async def test_performance_dict_carries_per_range_change(self):
        # The shared ``change_for_range`` helper produces:
        # - 1D from FMP's daily change (vs yesterday's close): 1.23 / 0.0065
        # - longer ranges from current price (189.84) vs first-bar close,
        #   where _chart_for_range encodes base = 100 + index*10.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        performance = result.model_payload["performance"]
        assert performance["1D"]["change_abs"] == pytest.approx(1.23)
        assert performance["1D"]["change_pct"] == pytest.approx(0.0065)
        # 1W: first bar close = 110, price = 189.84 → change_abs = 79.84
        assert performance["1W"]["change_abs"] == pytest.approx(79.84)
        # 1Y: first bar close = 150 → change_abs = 39.84
        assert performance["1Y"]["change_abs"] == pytest.approx(39.84)


class TestTiering:
    async def test_snapshot_default_trims_to_quote_and_performance(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        assert set(result.model_payload) == {"quote", "performance"}

    async def test_fundamentals_adds_the_fundamentals_bundle(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL", detail="fundamentals"), ctx
        )

        assert set(result.model_payload) == {
            "quote",
            "performance",
            "ratios",
            "valuation",
            "financials",
            "earnings",
            "analyst",
        }
        # profile + sector_context are full-only.
        assert "profile" not in result.model_payload
        assert "sector_context" not in result.model_payload

    async def test_full_returns_every_section(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL", detail="full"), ctx
        )

        assert set(result.model_payload) == {"performance", *_SAMPLE_RESPONSE}

    async def test_sections_override_returns_exactly_those_plus_base(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL", sections=["earnings"]), ctx
        )

        assert set(result.model_payload) == {"quote", "performance", "earnings"}

    async def test_sections_override_beats_detail(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL", detail="full", sections=["analyst"]),
            ctx,
        )

        assert set(result.model_payload) == {"quote", "performance", "analyst"}

    async def test_empty_sections_falls_through_to_detail(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL", detail="fundamentals", sections=[]),
            ctx,
        )

        assert set(result.model_payload) == {
            "quote",
            "performance",
            "ratios",
            "valuation",
            "financials",
            "earnings",
            "analyst",
        }

    async def test_internal_trace_keeps_full_payload_when_trimmed(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        # model_payload is trimmed to the snapshot tier...
        assert set(result.model_payload) == {"quote", "performance"}
        # ...but the audit trace carries every section plus performance.
        assert result.internal_trace is not None
        raw = result.internal_trace["raw"]
        assert set(raw) == {"performance", *_SAMPLE_RESPONSE}


class TestUnknownTicker:
    async def test_market_data_error_returns_error_payload_and_fails_pill(
        self,
    ):
        md = _market_data_mock(
            info_exc=MarketDataError("no data", symbol="BADTKR"),
        )
        ctx, emitter = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="BADTKR"), ctx
        )

        assert result.model_payload == {
            "error": "No data found for ticker BADTKR.",
            "ticker": "BADTKR",
        }
        assert result.internal_trace is None
        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "failed"

        # block_start(active) then block_data(failed) — same block_id.
        assert len(emitter.events) == 2
        assert emitter.events[0].block["state"] == "active"
        assert emitter.events[1].data["state"] == "failed"

    async def test_invalid_input_error_treated_as_unknown_ticker(self):
        md = _market_data_mock(
            info_exc=MarketDataInvalidInputError(
                "bad symbol", symbol="!!!"
            ),
        )
        ctx, _emitter = _make_ctx(market_data=md)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="!!!"), ctx
        )

        assert result.model_payload == {
            "error": "No data found for ticker !!!.",
            "ticker": "!!!",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"


class TestUpstreamFailures:
    @pytest.mark.parametrize(
        "exc",
        [
            MarketDataUnavailableError("timeout"),
            MarketDataUpstreamError("fmp 500", status_code=500),
        ],
    )
    async def test_provider_failures_return_temporary_error(self, exc):
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(side_effect=exc)
        ctx, emitter = _make_ctx(market_data=market_data)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        assert result.model_payload == {
            "error": "Market data provider is temporarily unavailable.",
            "ticker": "AAPL",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        assert emitter.events[-1].data["state"] == "failed"


class TestServiceUnavailable:
    async def test_market_data_none_returns_unavailable_payload(self):
        ctx, emitter = _make_ctx(market_data=None)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="AAPL"), ctx
        )

        assert result.model_payload == {
            "error": "Market data service is not configured in this environment.",
            "ticker": "AAPL",
        }
        assert result.ui_block is not None
        assert result.ui_block.state == "failed"
        # Pill still gets announced and flipped to failed.
        assert len(emitter.events) == 2
        assert isinstance(emitter.events[0], BlockStart)
        assert isinstance(emitter.events[1], BlockData)


class TestInputValidation:
    def test_empty_ticker_rejected(self):
        with pytest.raises(ValidationError):
            StockInfoInput(ticker="")

    def test_oversize_ticker_rejected(self):
        # 10-char cap is the upper bound — anything longer should fail.
        with pytest.raises(ValidationError):
            StockInfoInput(ticker="AAAAAAAAAAA")

    def test_lowercase_accepted_and_preserved(self):
        # Tool normalises to uppercase at execute() time; the input model
        # itself accepts whatever ticker the model emitted.
        validated = StockInfoInput(ticker="aapl")
        assert validated.ticker == "aapl"

    def test_detail_defaults_to_snapshot(self):
        validated = StockInfoInput(ticker="AAPL")
        assert validated.detail == "snapshot"
        assert validated.sections is None

    def test_invalid_detail_rejected(self):
        with pytest.raises(ValidationError):
            StockInfoInput(ticker="AAPL", detail="everything")

    def test_unknown_section_rejected(self):
        with pytest.raises(ValidationError):
            StockInfoInput(ticker="AAPL", sections=["bogus"])

    def test_valid_detail_and_sections_accepted(self):
        validated = StockInfoInput(
            ticker="AAPL", detail="full", sections=["earnings", "analyst"]
        )
        assert validated.detail == "full"
        assert validated.sections == ["earnings", "analyst"]
