import time
from unittest.mock import MagicMock

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
