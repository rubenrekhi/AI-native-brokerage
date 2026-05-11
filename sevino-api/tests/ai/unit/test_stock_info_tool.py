"""Unit tests for ``app.ai.tools.stock_info`` (``get_stock_info`` tool).

Covers the happy path plus every error branch the tool must handle so the
agent loop never crashes on a stock lookup:

* Happy path — pill goes active → complete, payload + internal_trace populated.
* Unknown ticker — ``MarketDataError`` mapped to error payload, pill failed.
* Invalid input from upstream — ``MarketDataInvalidInputError`` mapped likewise.
* Provider down — ``MarketDataUnavailableError`` returns "temporarily unavailable".
* Upstream non-2xx — ``MarketDataUpstreamError`` same.
* Missing service — ``ctx.http_clients.market_data is None`` (no FMP_API_KEY).
* Input validation — empty / oversize ticker rejected by Pydantic.
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
    "analyst": {"target_consensus": "220.50", "strong_buy": 12},
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


class TestHappyPath:
    async def test_returns_aggregated_payload_and_completes_pill(self):
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(return_value=_SAMPLE_RESPONSE)
        ctx, emitter = _make_ctx(market_data=market_data)

        result = await GetStockInfo().execute(
            StockInfoInput(ticker="aapl"), ctx
        )

        market_data.get_stock_info.assert_awaited_once_with("AAPL")
        assert result.model_payload == _SAMPLE_RESPONSE
        assert result.internal_trace == {"raw": _SAMPLE_RESPONSE}

        assert isinstance(result.ui_block, StatusBlock)
        assert result.ui_block.state == "complete"
        assert result.ui_block.label == "Pulling data on AAPL"

    async def test_emits_block_start_active_then_block_data_complete(self):
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(return_value=_SAMPLE_RESPONSE)
        ctx, emitter = _make_ctx(market_data=market_data)

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
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(return_value=_SAMPLE_RESPONSE)
        ctx, emitter = _make_ctx(market_data=market_data)

        await GetStockInfo().execute(StockInfoInput(ticker="msft"), ctx)

        assert emitter.events[0].block["label"] == "Pulling data on MSFT"
        market_data.get_stock_info.assert_awaited_once_with("MSFT")


class TestUnknownTicker:
    async def test_market_data_error_returns_error_payload_and_fails_pill(
        self,
    ):
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(
            side_effect=MarketDataError("no data", symbol="BADTKR")
        )
        ctx, emitter = _make_ctx(market_data=market_data)

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
        market_data = MagicMock()
        market_data.get_stock_info = AsyncMock(
            side_effect=MarketDataInvalidInputError(
                "bad symbol", symbol="!!!"
            )
        )
        ctx, _emitter = _make_ctx(market_data=market_data)

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
