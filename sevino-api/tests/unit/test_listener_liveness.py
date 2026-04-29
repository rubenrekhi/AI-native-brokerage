import time
from unittest.mock import MagicMock

from app.config import settings
from app.tasks.listener_liveness import check_listener_liveness


def _listener(stream: str, silence_seconds: float, threshold: float) -> MagicMock:
    """Build a fake listener whose last_message_received_at is
    ``silence_seconds`` ago, with the given silence threshold."""
    m = MagicMock()
    m.stream_name = stream
    m.last_message_received_at = time.monotonic() - silence_seconds
    m.silence_threshold_seconds = threshold
    return m


async def test_no_listeners_in_ctx_returns_zero_silent(monkeypatch):
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )

    result = await check_listener_liveness({})

    assert result == {"checked": 0, "silent": 0}
    capture.assert_not_called()


async def test_listener_within_threshold_does_not_alert(monkeypatch):
    """A listener that saw an event 30s ago with a 60s threshold is healthy
    — no Sentry alert, no 'silent' count."""
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    listener = _listener("account_status", silence_seconds=30, threshold=60)

    result = await check_listener_liveness({"listeners": [listener]})

    assert result == {"checked": 1, "silent": 0}
    capture.assert_not_called()


async def test_listener_over_threshold_fires_sentry_capture_message(monkeypatch):
    """A silent listener must escalate to Sentry via capture_message (not
    logger.warning — log-only warnings don't page anyone)."""
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    listener = _listener("trade_events_ws", silence_seconds=120, threshold=60)

    result = await check_listener_liveness({"listeners": [listener]})

    assert result == {"checked": 1, "silent": 1}
    capture.assert_called_once()
    # Verify the alert identifies the specific stream and says it's warning-level.
    args, kwargs = capture.call_args
    assert "trade_events_ws" in args[0]
    assert kwargs["level"] == "warning"


async def test_mixed_listeners_only_silent_ones_alert(monkeypatch):
    """Healthy and silent listeners coexist; only the silent ones fire Sentry."""
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    healthy = _listener("account_status", silence_seconds=10, threshold=300)
    silent = _listener("trade_events_sse", silence_seconds=500, threshold=60)

    result = await check_listener_liveness(
        {"listeners": [healthy, silent]}
    )

    assert result == {"checked": 2, "silent": 1}
    capture.assert_called_once()
    args, _ = capture.call_args
    assert "trade_events_sse" in args[0]
    assert "account_status" not in args[0]


async def test_silent_listener_sets_sentry_tags_and_context(monkeypatch):
    """Per be-auditor §11.3, every capture_message inside a long-running
    process must run within a new_scope that sets searchable tags. Without
    the sse_stream tag, ops can't filter silence alerts by stream in the
    Sentry UI — the stream name would only exist in the message text."""
    captured_tags: dict = {}
    captured_context: dict = {}

    class _FakeScope:
        def set_tag(self, k, v):
            captured_tags[k] = v

        def set_context(self, k, v):
            captured_context[k] = v

    class _FakeScopeManager:
        def __enter__(self):
            return _FakeScope()

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.new_scope",
        lambda: _FakeScopeManager(),
    )
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message",
        MagicMock(),
    )

    listener = _listener(
        "trade_events_ws", silence_seconds=250, threshold=60
    )
    await check_listener_liveness({"listeners": [listener]})

    assert captured_tags["sse_stream"] == "trade_events_ws"
    assert captured_tags["alert_type"] == "sse_silence"
    assert captured_context["sse_silence"]["stream"] == "trade_events_ws"
    assert captured_context["sse_silence"]["threshold_seconds"] == 60
    # silence_seconds is rounded but should reflect the 250s we passed in.
    assert captured_context["sse_silence"]["silence_seconds"] >= 249


async def test_every_silent_stream_fires_its_own_alert(monkeypatch):
    """Two silent streams = two separate Sentry events, one per stream, so
    alerts can be routed / silenced independently."""
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    a = _listener("account_status", silence_seconds=7200, threshold=3600)
    b = _listener("trade_events_ws", silence_seconds=300, threshold=60)

    result = await check_listener_liveness({"listeners": [a, b]})

    assert result == {"checked": 2, "silent": 2}
    assert capture.call_count == 2
    messages = [call.args[0] for call in capture.call_args_list]
    assert any("account_status" in m for m in messages)
    assert any("trade_events_ws" in m for m in messages)


async def test_pr_preview_env_skips_all_alerts(monkeypatch):
    """PR preview environments (RAILWAY_ENVIRONMENT_NAME=pr-*) must never
    fire Sentry silence alerts — these previews get torn down and their
    stale checkpoints generate noise. See SEV-433."""
    monkeypatch.setattr(settings, "railway_environment_name", "pr-123")
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    listener = _listener("trade_events_ws", silence_seconds=9999, threshold=60)

    result = await check_listener_liveness({"listeners": [listener]})

    assert result == {"checked": 0, "silent": 0, "skipped": "pr-preview"}
    capture.assert_not_called()


async def test_non_pr_railway_env_still_alerts(monkeypatch):
    """Non-PR Railway environments (staging, production) must still fire
    silence alerts normally."""
    monkeypatch.setattr(settings, "railway_environment_name", "staging")
    capture = MagicMock()
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message", capture
    )
    listener = _listener("account_status", silence_seconds=120, threshold=60)

    result = await check_listener_liveness({"listeners": [listener]})

    assert result == {"checked": 1, "silent": 1}
    capture.assert_called_once()


async def test_railway_env_tag_set_on_silence_alert(monkeypatch):
    """When RAILWAY_ENVIRONMENT_NAME is set (non-PR), it should appear as a
    tag on silence alerts for ops filtering."""
    monkeypatch.setattr(settings, "railway_environment_name", "staging")
    captured_tags: dict = {}

    class _FakeScope:
        def set_tag(self, k, v):
            captured_tags[k] = v

        def set_context(self, k, v):
            pass

    class _FakeScopeManager:
        def __enter__(self):
            return _FakeScope()

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.new_scope",
        lambda: _FakeScopeManager(),
    )
    monkeypatch.setattr(
        "app.tasks.listener_liveness.sentry_sdk.capture_message",
        MagicMock(),
    )

    listener = _listener("account_status", silence_seconds=200, threshold=60)
    await check_listener_liveness({"listeners": [listener]})

    assert captured_tags["railway_environment"] == "staging"
