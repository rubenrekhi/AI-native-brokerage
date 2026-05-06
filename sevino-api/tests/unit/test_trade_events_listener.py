from unittest.mock import AsyncMock, MagicMock

import pytest

from app.listeners.trade_events import TradeEventsListener
from app.services.alpaca_broker import AlpacaBrokerService


@pytest.fixture
def broker() -> AlpacaBrokerService:
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


@pytest.fixture
def listener(broker) -> TradeEventsListener:
    return TradeEventsListener(broker)


def test_listener_stream_config(listener):
    """These values are the single-consumer contract with Alpaca — drift
    here silently re-points the checkpoint, replays wrong events, or
    triggers a liveness storm. Guard them."""
    assert listener.stream_name == "trade_events_sse"
    assert listener.endpoint_path == "/v2/events/trades"
    assert listener.silence_threshold_seconds == 30 * 60
    # /v2/events/trades puts the ULID directly in the top-level event_id
    # field and accepts ?since_id=<ulid> on resume — not the legacy
    # event_ulid / since_ulid pair.
    assert listener.resume_field == "event_id"
    assert listener.resume_param == "since_id"


async def test_handle_event_delegates_to_shared_handler(listener, monkeypatch):
    """All trade-event variants route through ``handle_trade_update`` —
    no duplicate handler code."""
    fake = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.trade_events.handle_trade_update", fake
    )

    session = MagicMock()
    payload = {"order": {"id": "o_1", "status": "filled"}}
    await listener.handle_event(session, "fill", payload)

    fake.assert_awaited_once_with(session, payload, wire_format="sse")


async def test_on_reconnect_runs_reconcile_in_own_session(
    listener, monkeypatch
):
    """Reconcile runs outside the per-event transaction. The listener must
    open + commit its own session so the sweep's writes land."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.listeners.trade_events.async_session",
        MagicMock(return_value=ctx),
    )

    reconcile = AsyncMock(return_value=3)
    monkeypatch.setattr(
        "app.listeners.trade_events.reconcile_open_orders", reconcile
    )

    await listener.on_reconnect()

    reconcile.assert_awaited_once_with(
        session, listener._broker, stream_name="trade_events_sse"
    )
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_on_reconnect_rolls_back_on_reconcile_exception(
    listener, monkeypatch
):
    """A reconcile failure must roll the session back so no half-applied
    refresh leaks to the next connection's transaction. The exception
    propagates up — base_sse._stream_once handles Sentry capture so the
    stream stays connected."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.listeners.trade_events.async_session",
        MagicMock(return_value=ctx),
    )

    monkeypatch.setattr(
        "app.listeners.trade_events.reconcile_open_orders",
        AsyncMock(side_effect=RuntimeError("db blew up")),
    )

    with pytest.raises(RuntimeError):
        await listener.on_reconnect()

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_listener_registered_in_build_listeners():
    """Without registration, the worker startup hook never spawns the task."""
    from app.listeners.registry import build_listeners

    broker = AlpacaBrokerService.__new__(AlpacaBrokerService)
    listeners = build_listeners(broker)

    assert any(
        isinstance(listener, TradeEventsListener) for listener in listeners
    ), "TradeEventsListener must be returned by build_listeners()"
