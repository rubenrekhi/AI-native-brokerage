import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx_sse
import pytest
import structlog

from app.listeners.base_sse import BaseSSEListener
from app.services.alpaca_broker import AlpacaBrokerService


class _CaptureListener(BaseSSEListener):
    stream_name = "test_stream"
    endpoint_path = "/v1/events/test"
    silence_threshold_seconds = 60

    def __init__(self, broker):
        super().__init__(broker)
        self.handled: list[tuple[str, dict]] = []

    async def handle_event(self, session, event_type, data):
        self.handled.append((event_type, data))


def _sse(event: str, event_id: str | None, data: str) -> httpx_sse.ServerSentEvent:
    kwargs: dict = {"event": event, "data": data}
    if event_id is not None:
        kwargs["id"] = event_id
    return httpx_sse.ServerSentEvent(**kwargs)


@pytest.fixture
def broker():
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


@pytest.fixture
def listener(broker):
    return _CaptureListener(broker)


@pytest.fixture
def fake_session(monkeypatch):
    """Mocks ``app.listeners.base_sse.async_session`` to yield an AsyncMock
    session. Returns the mock session so tests can assert on commit/rollback."""
    session = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.listeners.base_sse.async_session", MagicMock(return_value=ctx)
    )
    return session


# --- _backoff (pure math) --------------------------------------------------


def test_backoff_initial_is_one_to_six_seconds():
    for _ in range(20):
        v = BaseSSEListener._backoff(0)
        assert 1.0 <= v < 6.0


def test_backoff_doubles_each_attempt():
    for _ in range(10):
        assert 2.0 <= BaseSSEListener._backoff(1) < 7.0
        assert 4.0 <= BaseSSEListener._backoff(2) < 9.0
        assert 8.0 <= BaseSSEListener._backoff(3) < 13.0


def test_backoff_caps_at_sixty_plus_jitter():
    for _ in range(20):
        v = BaseSSEListener._backoff(50)
        assert 60.0 <= v < 65.0


# --- _process_event happy path --------------------------------------------


async def test_process_event_calls_handler_and_upserts_checkpoint(
    listener, fake_session, monkeypatch
):
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    await listener._process_event(
        _sse("account_status", "evt_1", '{"account_id": "abc", "status": "ACTIVE"}')
    )

    assert listener.handled == [
        ("account_status", {"account_id": "abc", "status": "ACTIVE"})
    ]
    upsert.assert_awaited_once_with(fake_session, "test_stream", "evt_1")
    fake_session.commit.assert_awaited_once()
    fake_session.rollback.assert_not_awaited()


async def test_process_event_skips_checkpoint_when_event_id_missing(
    listener, fake_session, monkeypatch
):
    """Alpaca always includes an ID, but guard against malformed events that
    lack one — we can't anchor `since_id` to a missing ID, so skip it."""
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    await listener._process_event(_sse("account_status", None, '{"x": 1}'))

    assert listener.handled == [("account_status", {"x": 1})]
    upsert.assert_not_awaited()
    fake_session.commit.assert_awaited_once()


# --- _process_event failure modes -----------------------------------------


async def test_process_event_rolls_back_and_captures_on_handler_exception(
    broker, fake_session, monkeypatch
):
    """Handler exceptions must not kill the listener loop — they roll back
    the event's DB transaction (both handler writes AND checkpoint) and flow
    to Sentry."""

    class _Failing(BaseSSEListener):
        stream_name = "test_stream"
        endpoint_path = "/"
        silence_threshold_seconds = 60

        async def handle_event(self, session, event_type, data):
            raise RuntimeError("boom")

    listener = _Failing(broker)
    upsert = AsyncMock()
    capture = MagicMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.capture_exception", capture
    )

    # Does not raise — loop must keep running.
    await listener._process_event(_sse("account_status", "evt_2", '{"x": 1}'))

    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()
    capture.assert_called_once()


async def test_process_event_parse_failure_skips_handler_and_captures(
    listener, monkeypatch
):
    """Bad JSON on the wire should not kill the loop, hit the handler, or
    advance the checkpoint — we capture to Sentry and move on."""
    capture = MagicMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.capture_exception", capture
    )
    session_factory = MagicMock()
    monkeypatch.setattr("app.listeners.base_sse.async_session", session_factory)

    await listener._process_event(_sse("bad", "evt_x", "not json"))

    assert listener.handled == []
    session_factory.assert_not_called()
    capture.assert_called_once()


# --- correlation ID binding ------------------------------------------------


async def test_process_event_binds_correlation_id_to_contextvars(
    broker, fake_session, monkeypatch
):
    """Handlers must run with structlog contextvars set so every log line
    emitted during the handler carries stream + correlation_id + event_type."""
    captured: dict = {}

    class _CorrelationListener(BaseSSEListener):
        stream_name = "test_stream"
        endpoint_path = "/"
        silence_threshold_seconds = 60

        async def handle_event(self, session, event_type, data):
            captured.update(structlog.contextvars.get_contextvars())

    listener = _CorrelationListener(broker)
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    await listener._process_event(_sse("account_status", "evt_42", "{}"))

    assert captured["correlation_id"] == "sse-test_stream-evt_42"
    assert captured["stream"] == "test_stream"
    assert captured["event_type"] == "account_status"


# --- _load_checkpoint ------------------------------------------------------


async def test_load_checkpoint_returns_none_when_row_missing(
    listener, fake_session, monkeypatch
):
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )

    assert await listener._load_checkpoint() is None


async def test_load_checkpoint_returns_last_event_id_when_row_present(
    listener, fake_session, monkeypatch
):
    row = MagicMock()
    row.last_event_id = "evt_99"
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=row),
    )

    assert await listener._load_checkpoint() == "evt_99"


# --- run() reconnect loop --------------------------------------------------


async def test_run_reconnects_with_backoff_on_disconnect(listener, monkeypatch):
    call_count = 0

    async def _fake_stream_once(client):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("upstream blip")
        raise asyncio.CancelledError()

    sleeps: list[float] = []

    async def _fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(listener, "_stream_once", _fake_stream_once)
    monkeypatch.setattr("app.listeners.base_sse.asyncio.sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await listener.run()

    # Two failed attempts, each followed by a backoff sleep. Third attempt
    # raises CancelledError which propagates immediately — no trailing sleep.
    assert call_count == 3
    assert len(sleeps) == 2
    assert 1.0 <= sleeps[0] < 6.0  # attempt=0
    assert 2.0 <= sleeps[1] < 7.0  # attempt=1


async def test_run_propagates_cancelled_error_without_sleeping(listener, monkeypatch):
    async def _fake_stream_once(client):
        raise asyncio.CancelledError()

    async def _fake_sleep(_s):
        pytest.fail("should not sleep when the listener is cancelled")

    monkeypatch.setattr(listener, "_stream_once", _fake_stream_once)
    monkeypatch.setattr("app.listeners.base_sse.asyncio.sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await listener.run()
