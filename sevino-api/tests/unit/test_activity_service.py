"""Unit tests for ``app.services.activity.ActivityService``.

Covers the normalization the AI ``get_account_activity`` tool depends on:
unified feed across orders/transfers/dividends/interest, date windowing,
type + symbol filtering, signed amounts, per-type totals over the full window,
truncation, partial-source degradation, and the all-source-failure raise.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import app.services.activity as activity_mod
from app.exceptions import NotFoundError
from app.services.activity import ActivityService
from app.services.alpaca_broker import AlpacaBrokerUnavailableError

USER_ID = uuid.uuid4()
ACCOUNT_ID = "acc_test"


def _order(**o: Any) -> dict[str, Any]:
    return {
        "id": "o1",
        "symbol": "AAPL",
        "side": "buy",
        "status": "filled",
        "order_type": "market",
        "qty": "3",
        "filled_qty": "3",
        "filled_avg_price": "180.0700",
        "filled_at": "2026-05-20T14:31:00Z",
        **o,
    }


def _open_order(**o: Any) -> dict[str, Any]:
    return _order(
        id="open",
        symbol="TSLA",
        status="new",
        order_type="limit",
        qty="2",
        filled_qty="0",
        filled_avg_price=None,
        limit_price="180.00",
        filled_at=None,
        submitted_at="2026-05-19T10:00:00Z",
        **o,
    )


def _transfer(**t: Any) -> dict[str, Any]:
    return {
        "id": "t1",
        "direction": "INCOMING",
        "amount": "200.00",
        "status": "COMPLETE",
        "created_at": "2026-05-18T00:00:00Z",
        **t,
    }


def _dividend(**d: Any) -> dict[str, Any]:
    return {
        "id": "d1",
        "symbol": "MSFT",
        "net_amount": "3.12",
        "status": "executed",
        "created_at": "2026-05-15T00:00:00Z",
        **d,
    }


def _interest(**i: Any) -> dict[str, Any]:
    return {
        "id": "i1",
        "symbol": "SWEEPFDIC",
        "net_amount": "1.05",
        "status": "executed",
        "date": "2026-05-12",
        "description": "May Sweep",
        **i,
    }


@pytest.fixture
def patch_brokerage(monkeypatch):
    monkeypatch.setattr(
        activity_mod,
        "require_brokerage",
        AsyncMock(return_value=SimpleNamespace(alpaca_account_id=ACCOUNT_ID)),
    )


def _alpaca(
    *,
    orders: Any = None,
    transfers: Any = None,
    dividends: Any = None,
    interest: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        list_orders=AsyncMock(return_value=orders if orders is not None else []),
        list_transfers=AsyncMock(
            return_value=transfers if transfers is not None else []
        ),
        get_dividend_activities=AsyncMock(
            return_value=dividends if dividends is not None else []
        ),
        get_interest_activities=AsyncMock(
            return_value=interest if interest is not None else []
        ),
    )


async def _run(alpaca, **kwargs):
    return await ActivityService.get_activity(
        None, alpaca=alpaca, user_id=USER_ID, **kwargs
    )


class TestUnifiedFeed:
    async def test_merges_sorts_newest_first(self, patch_brokerage):
        alpaca = _alpaca(
            orders=[
                _order(id="o1", symbol="AAPL", filled_at="2026-05-20T14:31:00Z"),
                _order(
                    id="o2",
                    symbol="TSLA",
                    side="sell",
                    filled_qty="2",
                    filled_avg_price="250.00",
                    filled_at="2026-05-10T15:00:00Z",
                ),
            ],
            transfers=[_transfer(created_at="2026-05-18T00:00:00Z")],
            dividends=[_dividend(created_at="2026-05-15T00:00:00Z")],
            interest=[_interest(date="2026-05-12")],
        )

        result = await _run(alpaca)

        dates = [a["date"] for a in result["activities"]]
        assert dates == sorted(dates, reverse=True)
        assert result["count"] == 5
        assert {a["type"] for a in result["activities"]} == {
            "trade",
            "deposit",
            "dividend",
            "interest",
        }

    async def test_signed_amounts(self, patch_brokerage):
        alpaca = _alpaca(
            orders=[
                _order(id="b", symbol="AAPL", side="buy", filled_qty="3", filled_avg_price="180.07"),
                _order(id="s", symbol="TSLA", side="sell", filled_qty="2", filled_avg_price="250.00"),
            ],
            transfers=[
                _transfer(id="dep", direction="INCOMING", amount="200.00"),
                _transfer(id="wd", direction="OUTGOING", amount="50.00"),
            ],
        )

        result = await _run(alpaca)
        by_id = {a["symbol"] or a["type"]: a for a in result["activities"]}

        assert by_id["AAPL"]["amount"] == "-540.21"  # buy spends cash
        assert by_id["TSLA"]["amount"] == "500.00"  # sell returns cash
        assert by_id["deposit"]["amount"] == "200.00"
        assert by_id["withdrawal"]["amount"] == "-50.00"

    async def test_executed_and_pending_included_canceled_excluded_by_default(
        self, patch_brokerage
    ):
        alpaca = _alpaca(
            orders=[
                _order(id="filled", status="filled"),
                _order(id="partial", status="partially_filled"),
                _order(id="new", status="new"),
                _order(id="accepted", status="accepted"),
                _order(id="canceled", status="canceled"),
                _order(id="rejected", status="rejected"),
            ]
        )

        result = await _run(alpaca)

        statuses = {a["status"] for a in result["activities"]}
        # Executed + working orders show; terminal non-fills are dropped.
        assert statuses == {"filled", "partially_filled", "new", "accepted"}
        # Fills and working orders are counted separately.
        assert result["totals"]["executed_trades"] == 2
        assert result["totals"]["open_orders"] == 2

    async def test_include_canceled_surfaces_terminal_orders(self, patch_brokerage):
        alpaca = _alpaca(
            orders=[
                _order(id="filled", status="filled"),
                _order(id="canceled", status="canceled"),
                _order(id="rejected", status="rejected"),
            ]
        )

        result = await _run(alpaca, include_canceled=True)

        statuses = {a["status"] for a in result["activities"]}
        assert statuses == {"filled", "canceled", "rejected"}
        # Canceled/rejected count toward neither — only the one fill.
        assert result["totals"]["executed_trades"] == 1
        assert result["totals"]["open_orders"] == 0

    async def test_pending_close_orders_excluded_and_uncounted(
        self, patch_brokerage
    ):
        # pending_cancel / pending_replace are orders on their way out — a
        # cancel/replace was requested. They aren't working orders the user is
        # waiting on, so by default they drop from the feed and don't count as
        # open, just like terminal orders.
        alpaca = _alpaca(
            orders=[
                _order(id="filled", status="filled"),
                _order(id="working", status="new"),
                _order(id="canceling", status="pending_cancel"),
                _order(id="replacing", status="pending_replace"),
            ]
        )

        result = await _run(alpaca, types=["trade"])

        statuses = {a["status"] for a in result["activities"]}
        assert statuses == {"filled", "new"}
        assert result["totals"]["executed_trades"] == 1
        assert result["totals"]["open_orders"] == 1  # only the working order

    async def test_include_canceled_surfaces_pending_close_still_uncounted(
        self, patch_brokerage
    ):
        # On opt-in they surface (e.g. "what did I try to cancel?") but still
        # never inflate the open-orders count.
        alpaca = _alpaca(
            orders=[
                _order(id="filled", status="filled"),
                _order(id="canceling", status="pending_cancel"),
                _order(id="replacing", status="pending_replace"),
            ]
        )

        result = await _run(alpaca, types=["trade"], include_canceled=True)

        statuses = {a["status"] for a in result["activities"]}
        assert statuses == {"filled", "pending_cancel", "pending_replace"}
        assert result["totals"]["executed_trades"] == 1
        assert result["totals"]["open_orders"] == 0

    async def test_done_for_day_treated_as_open_not_terminal(self, patch_brokerage):
        # done_for_day pauses for today's session and resumes next trading day,
        # so a GTC/multi-day order is still live: it surfaces by default and
        # counts as open, unlike canceled/rejected which are dropped.
        alpaca = _alpaca(
            orders=[
                _order(id="filled", status="filled"),
                _order(
                    id="gtc",
                    symbol="TSLA",
                    status="done_for_day",
                    order_type="limit",
                    qty="2",
                    filled_qty="0",
                    filled_avg_price=None,
                    filled_at=None,
                    submitted_at="2026-05-19T10:00:00Z",
                ),
            ]
        )

        result = await _run(alpaca)

        statuses = {a["status"] for a in result["activities"]}
        assert statuses == {"filled", "done_for_day"}
        assert result["totals"]["executed_trades"] == 1
        assert result["totals"]["open_orders"] == 1

    async def test_partially_filled_done_for_day_keeps_fill_in_feed(
        self, patch_brokerage
    ):
        # A partial fill that then went done_for_day must not vanish — the row
        # surfaces with its executed quantity and cash amount intact.
        alpaca = _alpaca(
            orders=[
                _order(
                    id="partial_dfd",
                    symbol="TSLA",
                    side="sell",
                    status="done_for_day",
                    qty="5",
                    filled_qty="2",
                    filled_avg_price="250.00",
                )
            ]
        )

        result = await _run(alpaca)

        assert result["count"] == 1
        row = result["activities"][0]
        assert row["status"] == "done_for_day"
        assert row["filled_qty"] == "2"
        assert row["amount"] == "500.00"  # 2 sold @ 250, cash in
        assert result["totals"]["open_orders"] == 1

    async def test_working_order_row_carries_order_fields_and_null_fill(
        self, patch_brokerage
    ):
        alpaca = _alpaca(orders=[_open_order()])

        result = await _run(alpaca, types=["trade"])

        row = result["activities"][0]
        assert row["status"] == "new"
        assert row["order_type"] == "limit"
        assert row["qty"] == "2"
        assert row["filled_qty"] == "0"
        assert row["limit_price"] == "180.00"
        # No fill yet → no price or cash amount.
        assert row["price"] is None
        assert row["amount"] is None
        assert "180.00 limit" in row["summary"]
        # A working order is an open order, not a completed trade.
        assert result["totals"]["executed_trades"] == 0
        assert result["totals"]["open_orders"] == 1

    async def test_working_stop_order_carries_stop_price(self, patch_brokerage):
        alpaca = _alpaca(
            orders=[
                _order(
                    id="open",
                    symbol="TSLA",
                    status="new",
                    order_type="stop",
                    qty="2",
                    filled_qty="0",
                    filled_avg_price=None,
                    stop_price="150.00",
                    filled_at=None,
                    submitted_at="2026-05-19T10:00:00Z",
                )
            ]
        )

        result = await _run(alpaca, types=["trade"])

        row = result["activities"][0]
        assert row["order_type"] == "stop"
        assert row["stop_price"] == "150.00"
        assert "limit_price" not in row
        assert "150.00 stop" in row["summary"]

    async def test_negative_dividends_excluded(self, patch_brokerage):
        alpaca = _alpaca(
            dividends=[
                _dividend(id="pay", net_amount="3.12"),
                _dividend(id="withholding", net_amount="-0.50"),
            ]
        )

        result = await _run(alpaca)

        assert result["count"] == 1
        assert result["totals"]["dividends"] == "3.12"


class TestWindowing:
    async def test_excludes_out_of_window_records(self, patch_brokerage):
        alpaca = _alpaca(
            transfers=[
                _transfer(id="in", created_at="2026-05-18T00:00:00Z"),
                _transfer(id="out", created_at="2026-04-01T00:00:00Z"),
            ]
        )

        result = await _run(alpaca, after="2026-05-01", until="2026-05-31")

        assert result["count"] == 1
        assert result["activities"][0]["status"] == "COMPLETE"

    async def test_date_only_until_is_inclusive_to_end_of_day(self, patch_brokerage):
        alpaca = _alpaca(
            dividends=[_dividend(created_at="2026-05-31T18:00:00Z")]
        )

        result = await _run(alpaca, after="2026-05-01", until="2026-05-31")

        assert result["count"] == 1

    async def test_no_window_returns_everything(self, patch_brokerage):
        alpaca = _alpaca(
            transfers=[_transfer(created_at="2020-01-01T00:00:00Z")]
        )

        result = await _run(alpaca)

        assert result["count"] == 1
        assert result["range"] == {"after": None, "until": None}

    async def test_undated_record_excluded_when_windowed(self, patch_brokerage):
        alpaca = _alpaca(dividends=[_dividend(created_at=None, date=None)])

        windowed = await _run(alpaca, after="2026-05-01")
        unwindowed = await _run(alpaca)

        assert windowed["count"] == 0
        assert unwindowed["count"] == 1


class TestFilters:
    async def test_types_filter_only_calls_needed_sources(self, patch_brokerage):
        alpaca = _alpaca(orders=[_order()])

        result = await _run(alpaca, types=["trade"])

        alpaca.list_orders.assert_awaited_once()
        alpaca.list_transfers.assert_not_awaited()
        alpaca.get_dividend_activities.assert_not_awaited()
        alpaca.get_interest_activities.assert_not_awaited()
        assert "deposited" not in result["totals"]
        assert result["totals"] == {"executed_trades": 1, "open_orders": 0}

    async def test_deposit_type_excludes_withdrawals(self, patch_brokerage):
        alpaca = _alpaca(
            transfers=[
                _transfer(id="dep", direction="INCOMING", amount="200.00"),
                _transfer(id="wd", direction="OUTGOING", amount="50.00"),
            ]
        )

        result = await _run(alpaca, types=["deposit"])

        assert result["count"] == 1
        assert result["activities"][0]["type"] == "deposit"

    async def test_symbol_filters_dividends_and_skips_non_symbol_sources(
        self, patch_brokerage
    ):
        alpaca = _alpaca(
            orders=[_order(symbol="AAPL")],
            dividends=[
                _dividend(id="aapl", symbol="AAPL", net_amount="1.00"),
                _dividend(id="msft", symbol="MSFT", net_amount="2.00"),
            ],
            transfers=[_transfer()],
            interest=[_interest()],
        )

        result = await _run(alpaca, symbol="AAPL")

        # Orders are scoped server-side; assert we passed the ticker through.
        assert alpaca.list_orders.await_args.kwargs["symbols"] == "AAPL"
        # Transfers/interest can't match a ticker → never fetched.
        alpaca.list_transfers.assert_not_awaited()
        alpaca.get_interest_activities.assert_not_awaited()
        symbols = {a["symbol"] for a in result["activities"]}
        assert symbols == {"AAPL"}

    async def test_symbol_with_non_symbol_types_returns_note_not_silent_empty(
        self, patch_brokerage
    ):
        # A symbol pairs only with trades/dividends; requesting it alongside a
        # non-symbol type (deposit) filters every type out, so nothing is
        # fetched. Surface a note so the model explains the mismatch instead of
        # reporting an empty history.
        alpaca = _alpaca()
        result = await _run(alpaca, types=["deposit"], symbol="AAPL")

        alpaca.list_transfers.assert_not_awaited()
        assert result["count"] == 0
        assert result["totals"] == {}
        assert "AAPL" in result["note"]

        # A symbol-compatible request must not get the note.
        clean = await _run(_alpaca(orders=[_order(symbol="AAPL")]), symbol="AAPL")
        assert "note" not in clean


class TestServerSideBounding:
    async def test_dividend_and_interest_are_windowed_and_paginated(
        self, patch_brokerage
    ):
        alpaca = _alpaca()

        await _run(alpaca, after="2026-05-01", until="2026-05-31")

        for mock in (
            alpaca.get_dividend_activities,
            alpaca.get_interest_activities,
        ):
            kwargs = mock.await_args.kwargs
            assert kwargs["account_id"] == ACCOUNT_ID
            # The resolved window is pushed to Alpaca, not just filtered locally.
            assert kwargs["after"] == "2026-05-01T00:00:00+00:00"
            assert kwargs["until"] == "2026-05-31T23:59:59.999999+00:00"
            assert kwargs["paginate"] is True

    async def test_unwindowed_activities_pass_null_bounds_and_paginate(
        self, patch_brokerage
    ):
        alpaca = _alpaca()

        await _run(alpaca, types=["dividend"])

        kwargs = alpaca.get_dividend_activities.await_args.kwargs
        assert kwargs["after"] is None
        assert kwargs["until"] is None
        assert kwargs["paginate"] is True

    async def test_transfers_fetch_is_bounded_by_limit(self, patch_brokerage):
        alpaca = _alpaca()

        await _run(alpaca, types=["deposit", "withdrawal"])

        args, kwargs = alpaca.list_transfers.await_args
        assert args[0] == ACCOUNT_ID
        assert kwargs["limit"] == activity_mod._TRANSFER_FETCH_LIMIT
        # Both directions requested → no server-side direction narrowing.
        assert kwargs["direction"] is None

    async def test_single_transfer_type_narrows_direction(self, patch_brokerage):
        deposits = _alpaca()
        await _run(deposits, types=["deposit"])
        assert deposits.list_transfers.await_args.kwargs["direction"] == "INCOMING"

        withdrawals = _alpaca()
        await _run(withdrawals, types=["withdrawal"])
        assert (
            withdrawals.list_transfers.await_args.kwargs["direction"] == "OUTGOING"
        )


class TestTotalsAndTruncation:
    async def test_totals_cover_full_window_when_truncated(self, patch_brokerage):
        transfers = [
            _transfer(id=f"t{n}", amount="10.00", created_at=f"2026-05-{n:02d}T00:00:00Z")
            for n in range(1, 6)
        ]
        alpaca = _alpaca(transfers=transfers)

        result = await _run(alpaca, limit=2)

        assert result["count"] == 2
        assert result["matched"] == 5
        assert result["truncated"] is True
        # Totals sum all five deposits, not just the two returned.
        assert result["totals"]["deposited"] == "50.00"

    async def test_totals_omit_unfetched_sources(self, patch_brokerage):
        alpaca = _alpaca(dividends=[_dividend()])

        result = await _run(alpaca, types=["dividend"])

        assert set(result["totals"]) == {"dividends"}


class TestDegradation:
    async def test_partial_when_one_source_fails(self, patch_brokerage):
        alpaca = _alpaca(transfers=[_transfer()])
        alpaca.get_dividend_activities = AsyncMock(
            side_effect=AlpacaBrokerUnavailableError("boom")
        )

        result = await _run(alpaca, types=["deposit", "dividend"])

        assert result["partial"] is True
        assert "deposited" in result["totals"]
        assert "dividends" not in result["totals"]  # failed source omitted
        assert result["count"] == 1

    async def test_all_sources_fail_raises(self, patch_brokerage):
        alpaca = _alpaca()
        alpaca.list_transfers = AsyncMock(
            side_effect=AlpacaBrokerUnavailableError("boom")
        )

        with pytest.raises(AlpacaBrokerUnavailableError):
            await _run(alpaca, types=["deposit"])

    async def test_missing_brokerage_propagates_not_found(self, monkeypatch):
        monkeypatch.setattr(
            activity_mod,
            "require_brokerage",
            AsyncMock(side_effect=NotFoundError("no account")),
        )

        with pytest.raises(NotFoundError):
            await _run(_alpaca())

    async def test_no_partial_flag_on_clean_run(self, patch_brokerage):
        result = await _run(_alpaca(transfers=[_transfer()]), types=["deposit"])

        assert "partial" not in result
