"""Unit tests for ``app.ai.tools.display_stock_card``.

The tool's contract has several non-trivial pieces worth pinning:

* Happy path emits a fully-populated :class:`StockCardBlock` with the
  initial range's bars on ``bars`` and every range's bars on
  ``bars_by_range`` so iOS can swap chart data client-side.
* ``range`` input drives the initial timeframe; the card's ``range``
  field and ``bars`` reflect what the model asked for.
* ``expanded`` input gates the optional ``stats`` grid — false → None,
  true → populated from FMP quote/profile/ratios.
* ``color_state`` derives from the change sign with a ±1e-9 tolerance
  around zero for neutral.
* Partial chart failures drop only the failed range from ``bars_by_range``
  — the card still emits with whatever ranges succeeded. The initial
  range is load-bearing, though: if it fails the card is suppressed
  entirely.
* Every failure mode returns an error payload **without** a ``ui_block``
  so the model can apologise in text rather than the user seeing a
  half-rendered card.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai.blocks import StockCardBlock, StockStats
from app.ai.tools import ToolContext, ToolHttpClients
from app.ai.tools.display_stock_card import (
    DisplayStockCard,
    DisplayStockCardInput,
)
from app.ai.transport.events import Event
from app.exceptions import (
    MarketDataError,
    MarketDataInvalidInputError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)


_RANGES = ("1D", "1W", "1M", "3M", "6M", "1Y")


def _stock_info(*, change_percent: str = "0.65") -> dict[str, Any]:
    """Reference ``get_stock_info`` shape — string-valued money fields per
    the Sevino decimal-on-the-wire convention.
    """
    return {
        "quote": {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": "189.84",
            "change": "1.23",
            "change_percent": change_percent,
            "open": "188.00",
            "day_high": "190.00",
            "day_low": "187.50",
            "previous_close": "183.69",
            "year_high": "199.62",
            "year_low": "164.08",
            "volume": 50_000_000,
            "avg_volume": 60_000_000,
            "market_cap": 3_500_000_000_000,
            "pe_ratio": "23.45",
            "eps": "8.10",
        },
        "profile": {
            "name": "Apple Inc.",
            "logo_url": "https://example.com/logos/AAPL.png",
            "beta": "1.25",
            "exchange": "NASDAQ",
        },
        "ratios": {"dividend_yield": "0.0048"},
        "analyst": {},
    }


def _chart_for_range(range_label: str, *, n: int = 3) -> dict[str, Any]:
    """Build a ``_alpaca_bars`` projection where the close prices are
    range-specific (base price × range index) so tests can verify the
    tool routed the right chart into the right slot in ``bars_by_range``.
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

    ``get_chart`` differentiates by range: each call gets a chart whose
    close prices encode the range it was asked for, so tests can verify
    the tool routed the right chart into the right slot. Per-range
    failures can be injected via ``chart_exc_per_range``.
    """
    md = MagicMock()
    if info_exc is not None:
        md.get_stock_info = AsyncMock(side_effect=info_exc)
    else:
        md.get_stock_info = AsyncMock(return_value=info or _stock_info())

    chart_exc_per_range = chart_exc_per_range or {}

    async def _get_chart(symbol: str, range_label: str) -> dict[str, Any]:
        if range_label in chart_exc_per_range:
            raise chart_exc_per_range[range_label]
        return _chart_for_range(range_label)

    md.get_chart = AsyncMock(side_effect=_get_chart)
    return md


class TestHappyPath:
    async def test_emits_populated_stock_card_block_for_1d(self):
        # 1D is the special case where top-level change_abs / change_pct
        # come from FMP's daily quote (vs yesterday's close), not from
        # the first bar of the chart. Verify the daily numbers carry
        # through unchanged when the AI requests range="1D".
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="aapl", range="1D"), ctx
        )

        # ``get_stock_info`` fires once; ``get_chart`` fires once per
        # range option (six concurrent calls under the hood).
        md.get_stock_info.assert_awaited_once_with("AAPL")
        assert md.get_chart.await_count == len(_RANGES)
        chart_calls = {call.args for call in md.get_chart.await_args_list}
        assert chart_calls == {("AAPL", r) for r in _RANGES}

        # model_payload is a tiny ack — the model already has data from
        # its prior ``get_stock_info`` call and doesn't need it again.
        assert result.model_payload == {
            "displayed": True,
            "symbol": "AAPL",
            "range": "1D",
            "expanded": False,
        }
        assert isinstance(result.ui_block, StockCardBlock)

        card = result.ui_block
        assert card.symbol == "AAPL"
        assert card.company_name == "Apple Inc."
        assert card.logo_url == "https://example.com/logos/AAPL.png"
        assert card.price == pytest.approx(189.84)
        # For 1D, top-level change comes from FMP's daily quote.
        assert card.change_abs == pytest.approx(1.23)
        # FMP's "0.65" percent number → 0.0065 fraction on the wire.
        assert card.change_pct == pytest.approx(0.0065)
        assert card.color_state == "positive"
        assert card.range == "1D"
        assert card.range_options == list(_RANGES)
        # Compact card by default.
        assert card.stats is None

    async def test_top_level_change_for_non_1d_range_derives_from_bars(self):
        # For ranges other than 1D, top-level change_abs / change_pct
        # are computed from the chart bars: ``price - first_bar.close``.
        # First bar's close approximates N-time-ago's close — the
        # natural reference for "change over this range."
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range="1Y"), ctx
        )

        # _chart_for_range("1Y") has first.c = 100 + 5*10 = 150, price = 189.84.
        # Expected: change_abs = 189.84 - 150 = 39.84, change_pct = 39.84/150.
        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.range == "1Y"
        assert card.change_abs == pytest.approx(39.84)
        assert card.change_pct == pytest.approx(39.84 / 150.0)
        assert card.color_state == "positive"

    async def test_bars_field_matches_initial_range(self):
        # The top-level ``bars`` carries the initial range's bars so iOS
        # has something to render before it considers ``bars_by_range``.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range="1Y"), ctx
        )

        # _chart_for_range("1Y") encodes base price 100 + 5*10 = 150,
        # so close prices are 150, 151, 152.
        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.range == "1Y"
        assert [bar.c for bar in card.bars] == pytest.approx([150.0, 151.0, 152.0])

    async def test_bars_by_range_carries_change_per_range(self):
        # Each RangeBars entry bundles bars + per-range change values.
        # 1D's entry mirrors FMP's daily change (not bars-derived); other
        # ranges compute change from their own first bar's close.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.bars_by_range is not None
        by_range = {rb.range: rb for rb in card.bars_by_range}

        # 1D entry uses FMP's daily change (vs yesterday's close).
        assert by_range["1D"].change_abs == pytest.approx(1.23)
        assert by_range["1D"].change_pct == pytest.approx(0.0065)

        # Non-1D entries derive change from current price vs first bar
        # close. _chart_for_range encodes base = 100 + index*10.
        # 1W: first.c = 110, price = 189.84 → change_abs = 79.84
        # 1Y: first.c = 150, price = 189.84 → change_abs = 39.84
        assert by_range["1W"].change_abs == pytest.approx(79.84)
        assert by_range["1Y"].change_abs == pytest.approx(39.84)
        assert by_range["1Y"].change_pct == pytest.approx(39.84 / 150.0)

    async def test_bars_by_range_carries_every_range(self):
        # Slider switching on iOS reads from ``bars_by_range`` keyed by
        # the range label. Verify every requested range is present and
        # carries the right bars.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.bars_by_range is not None
        ranges_emitted = [rb.range for rb in card.bars_by_range]
        assert ranges_emitted == list(_RANGES)
        # Each range's bars are distinguishable by their close prices.
        for rb in card.bars_by_range:
            expected_base = 100.0 + (_RANGES.index(rb.range) * 10)
            assert [bar.c for bar in rb.bars] == pytest.approx(
                [expected_base, expected_base + 1, expected_base + 2]
            )

    async def test_internal_trace_carries_quote_and_ranges_loaded(self):
        # Audit row receives the quote payload + the list of ranges that
        # actually loaded, so a debugging operator can spot partial
        # failures without re-tokenising every chart.
        info = _stock_info()
        md = _market_data_mock(info=info)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert result.internal_trace == {
            "quote": info["quote"],
            "ranges_loaded": list(_RANGES),
        }

    async def test_no_sse_emit_before_ui_block_return(self):
        # The loop emits ``block_start`` + ``block_end`` for the returned
        # ``ui_block``. The tool itself must not pre-emit anything — no
        # status pill, no twin block_start.
        md = _market_data_mock()
        ctx, emitter = _make_ctx(market_data=md)

        await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert emitter.events == []


class TestRangeInput:
    @pytest.mark.parametrize("requested_range", list(_RANGES))
    async def test_initial_range_drives_card_range_and_bars(
        self, requested_range: str
    ):
        # The AI picks a range based on what it's answering; the card's
        # ``range`` field and top-level ``bars`` must reflect that pick
        # so iOS opens on the right view.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range=requested_range), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.range == requested_range
        expected_base = 100.0 + (_RANGES.index(requested_range) * 10)
        assert card.bars[0].c == pytest.approx(expected_base)

    async def test_range_defaults_to_1m(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.range == "1M"

    def test_invalid_range_rejected_by_pydantic(self):
        # The literal type closes the range set — anything outside it is
        # a wire-format violation and must fail loudly.
        with pytest.raises(ValidationError):
            DisplayStockCardInput(symbol="AAPL", range="YTD")  # type: ignore[arg-type]


class TestExpandedInput:
    async def test_expanded_false_omits_stats(self):
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", expanded=False), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.stats is None
        assert result.model_payload["expanded"] is False

    async def test_expanded_true_populates_stats_from_get_stock_info(self):
        # Stats are projected from the quote/profile/ratios the
        # ``get_stock_info`` call returned — no second fetch.
        md = _market_data_mock()
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", expanded=True), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert isinstance(card.stats, StockStats)
        # Money values arrive as decimal strings (decimal-on-the-wire);
        # counts arrive as ints.
        assert card.stats.open == "188.00"
        assert card.stats.year_high == "199.62"
        assert card.stats.volume == 50_000_000
        assert card.stats.market_cap == 3_500_000_000_000
        assert card.stats.pe_ratio == "23.45"
        assert card.stats.beta == "1.25"
        assert card.stats.dividend_yield == "0.0048"
        assert card.stats.exchange == "NASDAQ"
        assert result.model_payload["expanded"] is True

    async def test_stats_drops_zero_or_empty_fmp_values(self):
        # FMP's quote projection defaults missing money fields to "0"
        # and missing counts to 0 — surfacing those as real values
        # would show "$0.00" rows. Pin the ``_none_if_zero`` filter.
        info = _stock_info()
        info["quote"]["open"] = "0"          # placeholder
        info["quote"]["volume"] = 0          # int placeholder
        info["quote"]["eps"] = None          # legitimately null
        md = _market_data_mock(info=info)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", expanded=True), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert isinstance(card.stats, StockStats)
        # All three drop to None — iOS omits their rows.
        assert card.stats.open is None
        assert card.stats.volume is None
        assert card.stats.eps is None
        # Non-zero fields still carry through.
        assert card.stats.market_cap == 3_500_000_000_000


class TestColorState:
    @pytest.mark.parametrize(
        ("change_percent", "expected_state"),
        [
            ("0.65", "positive"),
            ("-0.65", "negative"),
            ("0", "neutral"),
            # Floating-point dust from FMP rounding shouldn't flip the
            # state on a flat day — pin the ±1e-9 tolerance.
            ("0.000000000001", "neutral"),
        ],
    )
    async def test_change_sign_maps_to_color(
        self, change_percent: str, expected_state: str
    ):
        # Pinned to range="1D" so the FMP quote's change_percent
        # directly drives the top-level color_state. Longer ranges
        # derive change from bars and would mask the daily sign.
        info = _stock_info(change_percent=change_percent)
        md = _market_data_mock(info=info)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range="1D"), ctx
        )

        assert isinstance(result.ui_block, StockCardBlock)
        assert result.ui_block.color_state == expected_state


class TestPartialChartFailures:
    async def test_non_initial_range_failure_drops_only_that_range(self):
        # Slider falls back to ``bars`` for ranges absent from
        # ``bars_by_range`` (iOS ``bars(for:)`` resolver). Verify a
        # single-range failure preserves the others rather than killing
        # the whole card.
        md = _market_data_mock(
            chart_exc_per_range={"6M": MarketDataUpstreamError("flaky", status_code=503)}
        )
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range="1M"), ctx
        )

        # Card still emits.
        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        # bars_by_range omits 6M but contains the other five.
        assert card.bars_by_range is not None
        ranges_emitted = [rb.range for rb in card.bars_by_range]
        assert "6M" not in ranges_emitted
        assert len(ranges_emitted) == len(_RANGES) - 1
        # internal_trace records which ranges actually loaded.
        assert "6M" not in result.internal_trace["ranges_loaded"]

    async def test_initial_range_failure_suppresses_card(self):
        # If the AI asked for "1Y" and 1Y is the only chart that failed,
        # we can't show the card — opening on a range with no data is
        # worse than not showing the card at all.
        md = _market_data_mock(
            chart_exc_per_range={
                "1Y": MarketDataError("no data", symbol="AAPL"),
            }
        )
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL", range="1Y"), ctx
        )

        # No card; error payload routes the apology back to the model.
        assert result.ui_block is None
        assert "error" in result.model_payload

    async def test_all_chart_ranges_failing_suppresses_card(self):
        # Pathological case — if every chart errors out, the initial
        # range is also missing so we suppress the card.
        all_fail = {r: MarketDataUpstreamError("down", status_code=500) for r in _RANGES}
        md = _market_data_mock(chart_exc_per_range=all_fail)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert result.ui_block is None
        assert "error" in result.model_payload


class TestUnknownTicker:
    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: MarketDataError("no data", symbol="BADTKR"),
            lambda: MarketDataInvalidInputError("bad symbol", symbol="BADTKR"),
        ],
    )
    async def test_info_lookup_error_returns_payload_with_no_ui_block(
        self, exc_factory
    ):
        # If ``get_stock_info`` itself fails the card has no quote/profile
        # to render — short-circuit and bubble the error to the model.
        md = _market_data_mock(info_exc=exc_factory())
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="BADTKR"), ctx
        )

        assert result.model_payload == {
            "error": "No data found for ticker BADTKR.",
            "symbol": "BADTKR",
        }
        assert result.ui_block is None


class TestUpstreamFailures:
    @pytest.mark.parametrize(
        "exc",
        [
            MarketDataUnavailableError("timeout"),
            MarketDataUpstreamError("fmp 500", status_code=500),
        ],
    )
    async def test_provider_failures_return_temporary_error(self, exc):
        md = _market_data_mock(info_exc=exc)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert result.model_payload == {
            "error": "Market data provider is temporarily unavailable.",
            "symbol": "AAPL",
        }
        assert result.ui_block is None


class TestServiceUnavailable:
    async def test_market_data_none_returns_unavailable_payload(self):
        # Dev / test environments without FMP_API_KEY have
        # ``market_data is None``. The tool reports the error to the
        # model without rendering a card.
        ctx, emitter = _make_ctx(market_data=None)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert result.model_payload == {
            "error": "Market data service is not configured in this environment.",
            "symbol": "AAPL",
        }
        assert result.ui_block is None
        assert emitter.events == []


class TestInputValidation:
    def test_empty_symbol_rejected(self):
        with pytest.raises(ValidationError):
            DisplayStockCardInput(symbol="")

    def test_oversize_symbol_rejected(self):
        with pytest.raises(ValidationError):
            DisplayStockCardInput(symbol="A" * 11)

    def test_lowercase_accepted_and_uppercased_at_execute(self):
        validated = DisplayStockCardInput(symbol="aapl")
        assert validated.symbol == "aapl"  # input model preserves raw


class TestEdgeCases:
    async def test_empty_bars_array_still_yields_card(self):
        # Pre-market or a brand-new IPO can return zero bars. The card
        # should still render — the iOS chart degrades to its empty
        # state rather than the tool returning an error.
        md = _market_data_mock()
        # Override every range to return zero bars.
        async def _empty_chart(symbol: str, range_label: str) -> dict[str, Any]:
            return {"symbol": symbol, "timeframe": range_label, "bars": []}

        md.get_chart = AsyncMock(side_effect=_empty_chart)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        card = result.ui_block
        assert isinstance(card, StockCardBlock)
        assert card.bars == []
        # bars_by_range still emitted (with empty per-range lists).
        assert card.bars_by_range is not None
        assert all(rb.bars == [] for rb in card.bars_by_range)
        # When bars are missing for a range, change_for_range falls back
        # to the daily quote's change. Every entry therefore carries the
        # 1D number; this is correct for "1D" but a known UX quirk for
        # longer ranges on a brand-new IPO (the card shows "1Y +1.16%"
        # which is actually today's daily change). Pin the behaviour so
        # a future "show nothing instead" change has to update the test.
        for rb in card.bars_by_range:
            assert rb.change_abs == pytest.approx(1.23)
            assert rb.change_pct == pytest.approx(0.0065)

    async def test_missing_logo_url_decodes_as_none(self):
        info = _stock_info()
        info["profile"]["logo_url"] = None
        md = _market_data_mock(info=info)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert isinstance(result.ui_block, StockCardBlock)
        assert result.ui_block.logo_url is None

    async def test_missing_company_name_falls_back_to_symbol(self):
        info = _stock_info()
        info["profile"]["name"] = ""
        md = _market_data_mock(info=info)
        ctx, _ = _make_ctx(market_data=md)

        result = await DisplayStockCard().execute(
            DisplayStockCardInput(symbol="AAPL"), ctx
        )

        assert isinstance(result.ui_block, StockCardBlock)
        assert result.ui_block.company_name == "AAPL"
