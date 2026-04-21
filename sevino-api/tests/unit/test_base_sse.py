import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
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


# --- Sentry scope tags on captured events ---------------------------------


async def test_process_event_tags_sentry_scope_with_stream_and_event_id(
    broker, fake_session, monkeypatch
):
    """When the handler throws, the Sentry event must be tagged with the
    stream/event_id/event_type so it's searchable in the Sentry UI. Without
    these tags, ops can't filter 'show me all errors on trade_events_sse'."""

    class _Failing(BaseSSEListener):
        stream_name = "trade_events_sse"
        endpoint_path = "/"
        silence_threshold_seconds = 60

        async def handle_event(self, session, event_type, data):
            raise RuntimeError("boom")

    listener = _Failing(broker)

    captured_tags: dict = {}
    captured_context: dict = {}

    class _FakeScope:
        def set_tag(self, k, v):
            captured_tags[k] = v

        def set_context(self, k, v):
            captured_context[k] = v

    fake_scope = _FakeScope()

    class _FakeScopeManager:
        def __enter__(self):
            return fake_scope

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.new_scope",
        lambda: _FakeScopeManager(),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.capture_exception", MagicMock()
    )

    await listener._process_event(_sse("order_fill", "evt_77", "{}"))

    assert captured_tags["sse_stream"] == "trade_events_sse"
    assert captured_tags["sse_event_id"] == "evt_77"
    assert captured_tags["sse_event_type"] == "order_fill"
    assert captured_context["sse_event"]["event_id"] == "evt_77"
    assert captured_context["sse_event"]["stream"] == "trade_events_sse"
    assert captured_context["sse_event"]["correlation_id"] == (
        "sse-trade_events_sse-evt_77"
    )


# --- CancelledError mid-handler rolls back then propagates -----------------


async def test_process_event_rolls_back_and_reraises_on_cancellation(
    broker, fake_session, monkeypatch
):
    """If the worker is cancelled while a handler is mid-flight, the open
    transaction must be rolled back explicitly — we don't rely on
    SQLAlchemy's shield-on-close — and CancelledError must propagate up so
    the listener loop terminates cleanly."""

    class _Cancelling(BaseSSEListener):
        stream_name = "test_stream"
        endpoint_path = "/"
        silence_threshold_seconds = 60

        async def handle_event(self, session, event_type, data):
            raise asyncio.CancelledError()

    listener = _Cancelling(broker)
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    with pytest.raises(asyncio.CancelledError):
        await listener._process_event(_sse("account_status", "evt_3", "{}"))

    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()


# --- _stream_once end-to-end via httpx.MockTransport -----------------------


async def test_stream_once_parses_canned_sse_and_advances_checkpoint(
    broker, fake_session, monkeypatch
):
    """Integration-shaped unit test: feed a real SSE byte stream through a
    MockTransport, assert the base class parses events, dispatches to the
    subclass handler, and upserts the checkpoint end-to-end."""

    # MockTransport intercepts all URLs, so we only need to pin the bearer
    # token — the actual base URL doesn't matter.
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok-xyz"))

    # Checkpoint starts empty → listener must not send ?since_id on first connect.
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    sse_body = (
        b"event: account_status\n"
        b"id: evt_100\n"
        b'data: {"account_id": "abc", "status": "ACTIVE"}\n'
        b"\n"
        b"event: account_status\n"
        b"id: evt_101\n"
        b'data: {"account_id": "def", "status": "REJECTED"}\n'
        b"\n"
    )

    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_body,
        )

    transport = httpx.MockTransport(_handler)

    listener = _CaptureListener(broker)
    # last_message_received_at is seeded to now() in __init__ — pin it so we
    # can assert it advances during the stream.
    listener.last_message_received_at = 0.0

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    # Two events handled, in order, with parsed JSON payloads.
    assert listener.handled == [
        ("account_status", {"account_id": "abc", "status": "ACTIVE"}),
        ("account_status", {"account_id": "def", "status": "REJECTED"}),
    ]
    # Checkpoint advanced to each event's ID as they were handled.
    assert upsert.await_count == 2
    assert upsert.await_args_list[0].args == (fake_session, "test_stream", "evt_100")
    assert upsert.await_args_list[1].args == (fake_session, "test_stream", "evt_101")
    # Liveness timestamp updated.
    assert listener.last_message_received_at > 0.0
    # Request carried the bearer and no `since_id` on first connect.
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.headers["authorization"] == "Bearer tok-xyz"
    assert req.headers["accept"] == "text/event-stream"
    assert "since_id" not in (req.url.query.decode() if req.url.query else "")


async def test_stream_once_raises_on_non_200_status(
    broker, fake_session, monkeypatch
):
    """If Alpaca returns a non-200 (401, 429, 5xx) — even with a
    text/event-stream content-type that would otherwise fool httpx-sse's
    content-type check — the listener must raise so run()'s backoff
    escalates. Without `raise_for_status`, the stream would drain to zero
    events and _stream_once would return normally, triggering a rapid
    attempt=0 reconnect loop."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok-xyz"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        # Worst case: 503 with the SSE content-type, which is the scenario
        # httpx-sse's content-type guard would silently allow through.
        return httpx.Response(
            503,
            headers={"content-type": "text/event-stream"},
            content=b"",
        )

    transport = httpx.MockTransport(_handler)
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await listener._stream_once(client)

    # Handler must not have been invoked for any events — we bailed before
    # entering the iteration loop.
    assert listener.handled == []


async def test_stream_once_sends_since_id_when_checkpoint_exists(
    broker, fake_session, monkeypatch
):
    """On reconnect after a disconnect/restart, the listener must replay from
    the last processed event by passing ``?since_id=<id>``."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok-xyz"))

    row = MagicMock()
    row.last_event_id = "evt_99"
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=b""
        )

    transport = httpx.MockTransport(_handler)
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    assert len(captured_requests) == 1
    assert "since_id=evt_99" in captured_requests[0].url.query.decode()
