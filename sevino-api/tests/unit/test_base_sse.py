import asyncio
from pathlib import Path
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
        _sse(
            "account_status",
            None,
            '{"event_ulid": "evt_1", "account_id": "abc", "status": "ACTIVE"}',
        )
    )

    assert listener.handled == [
        (
            "account_status",
            {"event_ulid": "evt_1", "account_id": "abc", "status": "ACTIVE"},
        )
    ]
    upsert.assert_awaited_once_with(fake_session, "test_stream", "evt_1")
    fake_session.commit.assert_awaited_once()
    fake_session.rollback.assert_not_awaited()


async def test_process_event_skips_checkpoint_when_event_ulid_missing(
    listener, fake_session, monkeypatch
):
    """Alpaca always includes an ID, but guard against malformed events that
    lack one — we can't anchor the resume param to a missing ID, so skip
    the checkpoint but still let the handler run and commit."""
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
    await listener._process_event(
        _sse("account_status", None, '{"event_ulid": "evt_2", "x": 1}')
    )

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

    await listener._process_event(_sse("bad", None, "not json"))

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

    await listener._process_event(
        _sse("account_status", None, '{"event_ulid": "evt_42"}')
    )

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

    await listener._process_event(
        _sse("order_fill", None, '{"event_ulid": "evt_77"}')
    )

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
        await listener._process_event(
            _sse("account_status", None, '{"event_ulid": "evt_3"}')
        )

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

    # Checkpoint starts empty → listener must not send a resume param on first
    # connect.
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
        b'data: {"event_ulid": "01HCM000000000000000000100", "account_id": "abc", "status": "ACTIVE"}\n'
        b"\n"
        b"event: account_status\n"
        b'data: {"event_ulid": "01HCM000000000000000000101", "account_id": "def", "status": "REJECTED"}\n'
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
        (
            "account_status",
            {
                "event_ulid": "01HCM000000000000000000100",
                "account_id": "abc",
                "status": "ACTIVE",
            },
        ),
        (
            "account_status",
            {
                "event_ulid": "01HCM000000000000000000101",
                "account_id": "def",
                "status": "REJECTED",
            },
        ),
    ]
    # Checkpoint advanced to each event's ULID as they were handled.
    assert upsert.await_count == 2
    assert upsert.await_args_list[0].args == (
        fake_session,
        "test_stream",
        "01HCM000000000000000000100",
    )
    assert upsert.await_args_list[1].args == (
        fake_session,
        "test_stream",
        "01HCM000000000000000000101",
    )
    # Liveness timestamp updated.
    assert listener.last_message_received_at > 0.0
    # Request carried the bearer and no resume param on first connect.
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.headers["authorization"] == "Bearer tok-xyz"
    assert req.headers["accept"] == "text/event-stream"
    query = req.url.query.decode() if req.url.query else ""
    assert "since_ulid" not in query
    assert "since_id" not in query


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


async def test_stream_once_sends_since_ulid_when_checkpoint_exists(
    broker, fake_session, monkeypatch
):
    """On reconnect after a disconnect/restart, the listener must replay from
    the last processed event by passing ``?since_ulid=<ulid>`` — the default
    resume param for legacy endpoints."""
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
    query = captured_requests[0].url.query.decode()
    assert "since_ulid=evt_99" in query
    assert "since_id=" not in query


async def test_stream_once_uses_overridden_resume_field_and_param(
    broker, fake_session, monkeypatch
):
    """Subclasses for already-migrated endpoints (`/v2/events/trades`,
    admin actions) must override `resume_field` and `resume_param`. Those
    endpoints put the ULID directly in the `event_id` JSON field and accept
    the resume value on the original `since_id` query param. This test
    verifies both knobs route through: the checkpoint is extracted from
    `data["event_id"]` and the reconnect URL carries `?since_id=<ulid>`."""

    class _V2TradeListener(BaseSSEListener):
        stream_name = "trade_events"
        endpoint_path = "/v2/events/trades"
        silence_threshold_seconds = 60
        resume_field = "event_id"
        resume_param = "since_id"

        def __init__(self, broker):
            super().__init__(broker)
            self.handled: list[tuple[str, dict]] = []

        async def handle_event(self, session, event_type, data):
            self.handled.append((event_type, data))

    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok-xyz"))

    row = MagicMock()
    row.last_event_id = "01HCMKKNRK7S5C1JYP50QGDECP"
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=row),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    sse_body = (
        b"event: fill\n"
        b'data: {"event_id": "01HCMKKNRK7S5C1JYP50QGDECQ", "order_id": "ord_1"}\n'
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
    listener = _V2TradeListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    # Reconnect URL uses the overridden query param name with the stored ULID.
    assert len(captured_requests) == 1
    query = captured_requests[0].url.query.decode()
    assert "since_id=01HCMKKNRK7S5C1JYP50QGDECP" in query
    assert "since_ulid=" not in query
    # Checkpoint upsert pulled the new ULID out of the `event_id` JSON field.
    upsert.assert_awaited_once_with(
        fake_session, "trade_events", "01HCMKKNRK7S5C1JYP50QGDECQ"
    )


# --- SSE comment handling (SEV-298) ---------------------------------------


def _sse_response(body: bytes) -> "httpx.Response":
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=body,
    )


def test_silence_threshold_default_is_90_seconds():
    """Default silence threshold is 90s: ~6x headroom on SSE-spec 15s
    heartbeats, sized to survive a few missed beats without false-alarming.
    Subclasses can still override — this only checks the base default."""
    assert BaseSSEListener.silence_threshold_seconds == 90


async def test_stream_once_heartbeat_bumps_liveness_without_dispatching_handler(
    broker, fake_session, monkeypatch
):
    """:heartbeat lines are the whole reason we read comments at all — they
    advance last_message_received_at on quiet streams so the liveness cron
    doesn't false-alarm. They must NOT hit the handler or advance the
    checkpoint."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    transport = httpx.MockTransport(
        lambda _req: _sse_response(b":heartbeat\n\n")
    )
    listener = _CaptureListener(broker)
    listener.last_message_received_at = 0.0

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    assert listener.handled == []
    upsert.assert_not_awaited()
    assert listener.last_message_received_at > 0.0


async def test_stream_once_heartbeat_emits_info_log(
    broker, fake_session, monkeypatch
):
    """Every heartbeat is info-logged with the stream name so worker logs
    give a live signal of connection health even on quiet streams."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    info_calls: list[tuple[str, dict]] = []

    def _capture_info(event: str, **kwargs):
        info_calls.append((event, kwargs))

    monkeypatch.setattr(
        "app.listeners.base_sse.logger.info", _capture_info
    )

    transport = httpx.MockTransport(
        lambda _req: _sse_response(b":heartbeat\n\n")
    )
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    heartbeat_logs = [
        (event, kwargs)
        for event, kwargs in info_calls
        if event == "sse_heartbeat"
    ]
    assert len(heartbeat_logs) == 1
    _, kwargs = heartbeat_logs[0]
    assert kwargs == {"stream": "test_stream"}


async def test_stream_once_diagnostic_comment_logs_and_breadcrumbs(
    broker, fake_session, monkeypatch
):
    """Non-heartbeat comments (e.g. Alpaca's v2 `: internal server error`)
    are logged at warning and added as a Sentry breadcrumb so they attach
    to any subsequent disconnect capture."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    breadcrumbs: list[dict] = []
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.add_breadcrumb",
        lambda **kwargs: breadcrumbs.append(kwargs),
    )

    warning_calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "app.listeners.base_sse.logger.warning",
        lambda event, **kwargs: warning_calls.append((event, kwargs)),
    )

    transport = httpx.MockTransport(
        lambda _req: _sse_response(b": internal server error\n\n")
    )
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    diag_warnings = [
        (event, kwargs)
        for event, kwargs in warning_calls
        if event == "sse_diagnostic_comment"
    ]
    assert len(diag_warnings) == 1
    _, kwargs = diag_warnings[0]
    assert kwargs["stream"] == "test_stream"
    assert kwargs["comment"] == "internal server error"

    diag_breadcrumbs = [
        b for b in breadcrumbs
        if b.get("category") == "sse"
        and b.get("level") == "warning"
        and "internal server error" in (b.get("message") or "")
    ]
    assert len(diag_breadcrumbs) == 1
    assert diag_breadcrumbs[0]["data"]["comment"] == "internal server error"


async def test_stream_once_dropped_messages_emits_sentry_capture_with_tag(
    broker, fake_session, monkeypatch
):
    """Alpaca's slow-client warning `: you are reading too slowly, dropped
    N messages` must raise its own Sentry event with the drop count as a
    searchable tag. A tag alone (riding on a future disconnect) would
    leave a silent gap if the connection stays up."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    captured_messages: list[tuple[str, str, dict]] = []
    captured_tags: dict = {}
    captured_contexts: dict = {}

    class _FakeScope:
        def set_tag(self, k, v):
            captured_tags[k] = v

        def set_context(self, k, v):
            captured_contexts[k] = v

    class _FakeScopeManager:
        def __enter__(self):
            return _FakeScope()

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.new_scope",
        lambda: _FakeScopeManager(),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.capture_message",
        lambda msg, level=None: captured_messages.append(
            (msg, level, dict(captured_tags))
        ),
    )

    transport = httpx.MockTransport(
        lambda _req: _sse_response(
            b": you are reading too slowly, dropped 10000 messages\n\n"
        )
    )
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    assert len(captured_messages) == 1
    msg, level, tags_snapshot = captured_messages[0]
    assert level == "warning"
    assert "10000" in msg
    assert "test_stream" in msg
    assert tags_snapshot["sse_stream"] == "test_stream"
    assert tags_snapshot["sse_dropped_messages"] == "10000"
    assert captured_contexts["sse_slow_client"]["dropped_messages"] == 10000


async def test_stream_once_mixed_events_and_comments(
    broker, fake_session, monkeypatch
):
    """End-to-end mixed stream: real events, a heartbeat, a slow-client
    warning, interleaved. All events reach the handler; liveness advances
    across the entire stream; the slow-client comment triggered its own
    Sentry capture."""
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "alpaca"
        / "account_status_mixed.sse"
    )
    sse_body = fixture.read_bytes()

    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    upsert = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", upsert
    )

    captured_messages: list[str] = []
    monkeypatch.setattr(
        "app.listeners.base_sse.sentry_sdk.capture_message",
        lambda msg, level=None: captured_messages.append(msg),
    )

    transport = httpx.MockTransport(lambda _req: _sse_response(sse_body))
    listener = _CaptureListener(broker)
    listener.last_message_received_at = 0.0

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    # Three real events reached the handler, in order.
    assert [evt for evt, _ in listener.handled] == [
        "account_status",
        "account_status",
        "account_status",
    ]
    assert [d["account_id"] for _, d in listener.handled] == [
        "abc",
        "def",
        "ghi",
    ]
    # Checkpoint advanced across all three events' ULIDs.
    assert upsert.await_count == 3
    assert upsert.await_args_list[-1].args[2] == (
        "01HCM000000000000000000003"
    )
    # Liveness updated.
    assert listener.last_message_received_at > 0.0
    # Slow-client comment produced a Sentry capture.
    assert any("dropped 10000" in msg for msg in captured_messages)


async def test_stream_once_comment_between_multiline_data_preserves_event(
    broker, fake_session, monkeypatch
):
    """The whole reason we intercept comments at the line layer (rather
    than letting SSEDecoder see them) is that a comment in the middle of
    a multi-line event must not tear the event. The SSEDecoder's internal
    state should survive the comment-skip and emit one event with both
    data lines joined on the terminating blank line."""
    monkeypatch.setattr(broker, "_get_token", AsyncMock(return_value="tok"))
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.get",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.listeners.base_sse.SseCheckpointRepository.upsert", AsyncMock()
    )

    # One event with two data: lines, a :heartbeat comment wedged between
    # them. Per the SSE spec, the two data values are joined with "\n" on
    # emit. The expected handler payload is {"a": 1, "b": 2} only if
    # both data lines reach the decoder despite the comment.
    sse_body = (
        b"event: account_status\n"
        b'data: {"event_ulid": "01HCM00000000000000000MULT",\n'
        b":heartbeat\n"
        b'data:  "a": 1, "b": 2}\n'
        b"\n"
    )

    transport = httpx.MockTransport(lambda _req: _sse_response(sse_body))
    listener = _CaptureListener(broker)

    async with httpx.AsyncClient(transport=transport) as client:
        await listener._stream_once(client)

    # Exactly one event reached the handler — the comment did not split
    # the frame into two malformed halves.
    assert len(listener.handled) == 1
    event_type, data = listener.handled[0]
    assert event_type == "account_status"
    # And the data payload round-tripped correctly across the interleaved
    # comment (SSEDecoder joins multi-line data: with "\n").
    assert data == {
        "event_ulid": "01HCM00000000000000000MULT",
        "a": 1,
        "b": 2,
    }
