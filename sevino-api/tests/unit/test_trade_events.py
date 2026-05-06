import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.order_event import OpenOrderRow
from app.services import trade_events
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)


# --- STATUS_ORDER ----------------------------------------------------------


def test_status_order_terminal_states_share_top_rank():
    """Terminal states are mutually exclusive outcomes — if one lands, no
    other terminal transition can follow, so they share the max ordinal.
    Partial fills sit strictly below."""
    terminal = {"filled", "canceled", "expired", "rejected"}
    ranks = {s: trade_events.STATUS_ORDER[s] for s in terminal}
    assert len(set(ranks.values())) == 1
    max_rank = next(iter(ranks.values()))
    assert trade_events.STATUS_ORDER["partially_filled"] < max_rank
    assert trade_events.STATUS_ORDER["new"] < max_rank


def test_status_order_covers_alpaca_lifecycle():
    """Any unknown status should be treated as "apply anyway, don't skip" —
    codify the set we explicitly rank so a regression that drops one is
    caught by this test, not by silently regressing a live order."""
    required = {
        "new",
        "accepted",
        "pending_new",
        "partially_filled",
        "filled",
        "done_for_day",
        "canceled",
        "expired",
        "replaced",
        "pending_cancel",
        "pending_replace",
        "rejected",
    }
    missing = required - set(trade_events.STATUS_ORDER)
    assert missing == set(), f"missing lifecycle statuses: {missing}"


# --- handle_trade_update skip conditions -----------------------------------


def _row(
    *,
    status: str = "new",
    filled_avg_price=None,
    filled_qty=None,
    filled_at=None,
) -> MagicMock:
    row = MagicMock()
    row.alpaca_order_id = "o_1"
    row.status = status
    row.filled_avg_price = filled_avg_price
    row.filled_qty = filled_qty
    row.filled_at = filled_at
    return row


async def test_handle_missing_order_id_is_noop(monkeypatch):
    get = AsyncMock()
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        get,
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(session, {"event": "fill"})

    get.assert_not_awaited()
    session.flush.assert_not_awaited()


async def test_handle_unknown_alpaca_order_id_is_noop(monkeypatch):
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=None),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session, {"order": {"id": "o_unknown", "status": "filled"}}
    )

    session.flush.assert_not_awaited()


async def test_handle_skips_when_incoming_status_older(monkeypatch):
    """``on_reconnect`` REST reconcile wrote ``filled``; a replayed SSE
    ``partially_filled`` (an earlier intermediate event that fell within the
    ``since_id`` replay window) for the same order must not regress the row."""
    row = _row(status="filled", filled_qty=Decimal("10"))
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {
            "order": {
                "id": "o_1",
                "status": "partially_filled",
                "filled_qty": "5",
            }
        },
    )

    assert row.status == "filled"
    assert row.filled_qty == Decimal("10")
    session.flush.assert_not_awaited()


async def test_handle_applies_when_incoming_status_newer(monkeypatch):
    row = _row(status="new")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {
            "order": {
                "id": "o_1",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "150.25",
                "filled_at": "2026-04-20T16:30:00Z",
            }
        },
    )

    assert row.status == "filled"
    assert row.filled_qty == Decimal("10")
    assert row.filled_avg_price == Decimal("150.25")
    assert row.filled_at == datetime(2026, 4, 20, 16, 30, tzinfo=timezone.utc)
    session.flush.assert_awaited_once()


async def test_handle_idempotent_same_terminal_status(monkeypatch):
    """Reconcile and SSE both deliver ``filled`` for the same order — the
    second write must be a no-op at the ordering level (same status) so it
    doesn't bump anything. Fill fields may still re-apply (idempotent
    assignment)."""
    row = _row(
        status="filled",
        filled_qty=Decimal("10"),
        filled_avg_price=Decimal("150.25"),
    )
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {
            "order": {
                "id": "o_1",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "150.25",
            }
        },
    )

    assert row.status == "filled"
    assert row.filled_qty == Decimal("10")
    assert row.filled_avg_price == Decimal("150.25")


async def test_handle_accepts_payload_with_or_without_order_wrapper(monkeypatch):
    """Live trade events wrap the order under ``order``; REST ``get_order``
    returns it at the top level. The handler must accept both."""
    row = _row(status="new")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    # Top-level shape (REST).
    await trade_events.handle_trade_update(
        session, {"id": "o_1", "status": "accepted"}
    )

    assert row.status == "accepted"


async def test_handle_sse_payload_missing_order_wrapper_is_skipped_loudly(monkeypatch):
    """An SSE payload without the ``order`` wrapper is malformed. It must
    not silently fall through to the envelope (which would let the
    envelope's own ``event_id`` impersonate an Alpaca order id and update
    the wrong row). Instead it skips, logs a warning, and surfaces a
    Sentry event so a wire-format regression is caught."""
    repo_get = AsyncMock()
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        repo_get,
    )
    capture = MagicMock()
    monkeypatch.setattr(trade_events.sentry_sdk, "capture_message", capture)
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {"event": "fill", "event_id": "ulid_42", "id": "ulid_42"},
        wire_format="sse",
    )

    # Repository was never queried — we bailed before the lookup.
    repo_get.assert_not_awaited()
    session.flush.assert_not_awaited()
    capture.assert_called_once()
    assert capture.call_args.kwargs.get("level") == "warning"


async def test_handle_rest_payload_without_wrapper_is_accepted(monkeypatch):
    """REST ``get_order`` returns the order at the top level, not wrapped.
    With ``wire_format='rest'`` the handler must accept that shape and
    apply the update — only the SSE path requires the wrapper."""
    row = _row(status="new")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {"id": "o_1", "status": "accepted"},
        wire_format="rest",
    )

    assert row.status == "accepted"
    session.flush.assert_awaited_once()


async def test_handle_unknown_status_is_applied(monkeypatch):
    """An Alpaca lifecycle change that predates our STATUS_ORDER map must not
    silently drop. Apply it and surface via logs — better a write we can
    trace than silent regression."""
    row = _row(status="new")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session, {"order": {"id": "o_1", "status": "some_new_alpaca_status"}}
    )

    assert row.status == "some_new_alpaca_status"


# --- Terminal-state peer skip ---------------------------------------------


async def test_handle_skips_peer_terminal_status(monkeypatch):
    """Terminal statuses (filled/canceled/expired/rejected) are mutually
    exclusive and write-once — once a row is ``filled``, a subsequent
    ``rejected`` event (e.g. from a replayed prior terminal that lost a race
    elsewhere) must not overwrite it. Critical because the rest of the
    system treats these as final."""
    row = _row(status="filled", filled_qty=Decimal("10"))
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {"order": {"id": "o_1", "status": "rejected"}},
    )

    assert row.status == "filled"
    session.flush.assert_not_awaited()


async def test_handle_allows_peer_non_terminal_lateral_transition(monkeypatch):
    """Non-terminal peers (e.g. pending_cancel → pending_replace at rank 2)
    are legitimately unordered Alpaca states — applying whichever arrived
    last is the correct Alpaca-truth view."""
    row = _row(status="pending_cancel")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    await trade_events.handle_trade_update(
        session,
        {"order": {"id": "o_1", "status": "pending_replace"}},
    )

    assert row.status == "pending_replace"
    session.flush.assert_awaited_once()


# --- reconcile_open_orders -------------------------------------------------


@pytest.fixture
def broker() -> AlpacaBrokerService:
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


async def test_reconcile_no_open_orders_returns_zero(broker, monkeypatch):
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(return_value=[]),
    )
    session = MagicMock()

    count = await trade_events.reconcile_open_orders(
        session, broker, stream_name="trade_events_sse"
    )

    assert count == 0


async def test_reconcile_refreshes_each_open_order(broker, monkeypatch):
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_a.user_id = uuid.uuid4()
    row_b = _row(status="partially_filled", filled_qty=Decimal("5"))
    row_b.alpaca_order_id = "o_b"
    row_b.user_id = uuid.uuid4()

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    remote_map = {
        ("acct_a", "o_a"): {
            "id": "o_a",
            "status": "filled",
            "filled_qty": "1",
        },
        ("acct_b", "o_b"): {
            "id": "o_b",
            "status": "filled",
            "filled_qty": "10",
        },
    }

    async def _fake_get_order(account_id, order_id):
        return remote_map[(account_id, order_id)]

    monkeypatch.setattr(broker, "get_order", _fake_get_order)

    applied: list[tuple[str, str]] = []

    async def _fake_handle(session, payload, **_kwargs):
        applied.append((payload["id"], payload["status"]))

    monkeypatch.setattr(trade_events, "handle_trade_update", _fake_handle)

    # Stub async_session so each apply runs through a no-op context manager.
    def _make_session():
        s = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    monkeypatch.setattr(trade_events, "async_session", _make_session)

    session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        session, broker, stream_name="trade_events_sse"
    )

    assert count == 2
    assert applied == [("o_a", "filled"), ("o_b", "filled")]


async def test_reconcile_skips_failed_fetch(broker, monkeypatch):
    """One unreachable order shouldn't block the rest of the sweep."""
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_a.user_id = uuid.uuid4()
    row_b = _row(status="new")
    row_b.alpaca_order_id = "o_b"
    row_b.user_id = uuid.uuid4()

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    async def _fake_get_order(account_id, order_id):
        if order_id == "o_a":
            raise AlpacaBrokerUnavailableError("timeout")
        return {"id": order_id, "status": "filled"}

    monkeypatch.setattr(broker, "get_order", _fake_get_order)

    applied: list[str] = []

    async def _fake_handle(session, payload, **_kwargs):
        applied.append(payload["id"])

    monkeypatch.setattr(trade_events, "handle_trade_update", _fake_handle)

    def _make_session():
        s = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    monkeypatch.setattr(trade_events, "async_session", _make_session)

    session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        session, broker, stream_name="trade_events_sse"
    )

    # o_a was skipped, o_b succeeded.
    assert count == 1
    assert applied == ["o_b"]


async def test_reconcile_one_failed_apply_does_not_poison_rest_of_sweep(
    broker, monkeypatch
):
    """If one order's handle_trade_update raises (e.g. a DB flush error), the
    surrounding sweep must keep going — the per-order session pattern
    isolates the failure so subsequent orders land."""
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_a.user_id = uuid.uuid4()
    row_b = _row(status="new")
    row_b.alpaca_order_id = "o_b"
    row_b.user_id = uuid.uuid4()

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    async def _fake_get_order(account_id, order_id):
        return {"id": order_id, "status": "filled"}

    monkeypatch.setattr(broker, "get_order", _fake_get_order)

    applied: list[str] = []

    async def _fake_handle(apply_session, payload, **_kwargs):
        if payload["id"] == "o_a":
            raise RuntimeError("simulated flush failure on o_a")
        applied.append(payload["id"])

    monkeypatch.setattr(trade_events, "handle_trade_update", _fake_handle)

    # Track per-session commit/rollback so we can assert isolation.
    per_order_sessions: list[AsyncMock] = []

    def _make_session():
        s = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=None)
        per_order_sessions.append(s)
        return ctx

    monkeypatch.setattr(trade_events, "async_session", _make_session)

    read_session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        read_session, broker, stream_name="trade_events_sse"
    )

    # o_a failed + rolled back; o_b committed.
    assert count == 1
    assert applied == ["o_b"]
    assert len(per_order_sessions) == 2
    per_order_sessions[0].rollback.assert_awaited_once()
    per_order_sessions[0].commit.assert_not_awaited()
    per_order_sessions[1].commit.assert_awaited_once()
    per_order_sessions[1].rollback.assert_not_awaited()


async def test_reconcile_emits_alert_when_every_fetch_fails(broker, monkeypatch):
    """Every-fetch-fail is a silent gap that neither per-order breadcrumbs
    nor the listener's reconnect logs will alert on — surface it with one
    scoped capture_message per empty sweep so ops can page on it."""
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_b = _row(status="new")
    row_b.alpaca_order_id = "o_b"

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    async def _always_fail(account_id, order_id):
        raise AlpacaBrokerUnavailableError("alpaca down")

    monkeypatch.setattr(broker, "get_order", _always_fail)

    capture = MagicMock()
    monkeypatch.setattr(trade_events.sentry_sdk, "capture_message", capture)

    read_session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        read_session, broker, stream_name="trade_events_sse"
    )

    assert count == 0
    capture.assert_called_once()
    message_arg = capture.call_args.args[0]
    assert "all 2" in message_arg
    assert capture.call_args.kwargs.get("level") == "warning"


async def test_reconcile_emits_alert_on_partial_fetch_failure(broker, monkeypatch):
    """Partial outages (some fetches fail, some succeed) must also escalate —
    a sustained 50%-fail Alpaca outage would otherwise stay silent because
    per-order ``add_breadcrumb`` calls don't surface as Sentry events."""
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_b = _row(status="new")
    row_b.alpaca_order_id = "o_b"

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    async def _half_fail(account_id, order_id):
        if order_id == "o_a":
            raise AlpacaBrokerUnavailableError("timeout")
        return {"id": order_id, "status": "filled"}

    monkeypatch.setattr(broker, "get_order", _half_fail)

    async def _fake_handle(session, payload, **_kwargs):
        pass

    monkeypatch.setattr(trade_events, "handle_trade_update", _fake_handle)

    def _make_session():
        s = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    monkeypatch.setattr(trade_events, "async_session", _make_session)

    capture = MagicMock()
    monkeypatch.setattr(trade_events.sentry_sdk, "capture_message", capture)

    read_session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        read_session, broker, stream_name="trade_events_sse"
    )

    assert count == 1
    capture.assert_called_once()
    message_arg = capture.call_args.args[0]
    assert "1 fetch" in message_arg
    assert "2 orders" in message_arg
    assert capture.call_args.kwargs.get("level") == "warning"


async def test_reconcile_skips_and_alerts_on_id_mismatch(broker, monkeypatch):
    """If Alpaca returns an order body whose ``id`` doesn't match what we
    asked for, ``handle_trade_update`` would otherwise UPDATE whichever row
    matches the returned id — possibly belonging to another user. The
    reconcile sweep must skip the response and surface a Sentry event."""
    row_a = _row(status="new")
    row_a.alpaca_order_id = "o_a"
    row_b = _row(status="new")
    row_b.alpaca_order_id = "o_b"

    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_open_with_alpaca_account_id",
        AsyncMock(
            return_value=[
                OpenOrderRow(order=row_a, alpaca_account_id="acct_a"),
                OpenOrderRow(order=row_b, alpaca_account_id="acct_b"),
            ]
        ),
    )

    async def _wrong_id(account_id, order_id):
        if order_id == "o_a":
            return {"id": "o_OTHER", "status": "filled"}
        return {"id": order_id, "status": "filled"}

    monkeypatch.setattr(broker, "get_order", _wrong_id)

    applied: list[str] = []

    async def _fake_handle(session, payload, **_kwargs):
        applied.append(payload["id"])

    monkeypatch.setattr(trade_events, "handle_trade_update", _fake_handle)

    def _make_session():
        s = AsyncMock()
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=s)
        ctx.__aexit__ = AsyncMock(return_value=None)
        return ctx

    monkeypatch.setattr(trade_events, "async_session", _make_session)

    capture = MagicMock()
    monkeypatch.setattr(trade_events.sentry_sdk, "capture_message", capture)

    read_session = MagicMock()
    count = await trade_events.reconcile_open_orders(
        read_session, broker, stream_name="trade_events_sse"
    )

    # Only o_b applied; o_a's mismatched response was skipped.
    assert count == 1
    assert applied == ["o_b"]
    # The per-row id mismatch is recorded as a breadcrumb (no Sentry
    # event fanned out per bad row), and the sweep-end alert fires once
    # with the failure breakdown. capture_message therefore fires once
    # with level=warning and the message includes "id-mismatch".
    assert capture.call_count == 1
    assert capture.call_args.kwargs.get("level") == "warning"
    assert "id-mismatch" in capture.call_args.args[0]


# --- REST reconcile + SSE replay converge on identical DB state ------------


async def test_reconcile_then_sse_replay_converge_to_same_row_state(monkeypatch):
    """Acceptance criterion: the ``on_reconnect`` REST reconcile sweep and
    the subsequent ``since_id`` SSE replay both route through the same
    handler, and together they converge on the Alpaca-truth row state with
    no double-applied fills or status regressions. This replays a realistic
    lifecycle (new → accepted → partially_filled → filled) where the
    reconcile write lands first with the terminal state and the SSE replay
    lags with earlier intermediate events."""
    row = _row(status="new")
    monkeypatch.setattr(
        trade_events.OrderEventRepository,
        "get_by_alpaca_order_id",
        AsyncMock(return_value=row),
    )
    session = MagicMock()
    session.flush = AsyncMock()

    # REST reconcile sweep ran first and wrote "filled".
    await trade_events.handle_trade_update(
        session,
        {
            "order": {
                "id": "o_1",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "150.25",
            }
        },
    )
    assert row.status == "filled"

    # SSE now replays the same lifecycle events from ``since_id``. None of
    # them may regress the terminal state, and the final state must match
    # what reconcile wrote — exactly-once, by UPDATE idempotency + the
    # STATUS_ORDER ordering skip.
    for stale_event in (
        {"order": {"id": "o_1", "status": "new"}},
        {"order": {"id": "o_1", "status": "accepted"}},
        {"order": {"id": "o_1", "status": "partially_filled", "filled_qty": "5"}},
        {
            "order": {
                "id": "o_1",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "150.25",
            }
        },
    ):
        await trade_events.handle_trade_update(session, stale_event)

    assert row.status == "filled"
    assert row.filled_qty == Decimal("10")
    assert row.filled_avg_price == Decimal("150.25")
