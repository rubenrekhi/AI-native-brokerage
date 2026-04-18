"""Unit tests for correlation ID and request logging middleware."""

from unittest.mock import MagicMock, patch

import pytest
import structlog
from structlog.testing import capture_logs
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.middleware.api_key import APIKeyMiddleware, _EXEMPT_PATHS
from app.middleware.correlation import CORRELATION_HEADER, CorrelationIDMiddleware
from app.middleware.logging import RequestLoggingMiddleware


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(headers: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "server": ("testserver", 80),
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# CorrelationIDMiddleware
# ---------------------------------------------------------------------------

async def test_generates_correlation_id_when_absent():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    request = _make_request()
    response = Response()

    async def call_next(req):
        assert hasattr(req.state, "correlation_id")
        assert len(req.state.correlation_id) == 32  # uuid4 hex
        return response

    resp = await middleware.dispatch(request, call_next)
    assert CORRELATION_HEADER in resp.headers
    assert len(resp.headers[CORRELATION_HEADER]) == 32


async def test_reuses_incoming_correlation_id():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    incoming_id = "my-trace-id-123"
    request = _make_request(headers={CORRELATION_HEADER: incoming_id})
    response = Response()

    async def call_next(req):
        assert req.state.correlation_id == incoming_id
        return response

    resp = await middleware.dispatch(request, call_next)
    assert resp.headers[CORRELATION_HEADER] == incoming_id


async def test_binds_correlation_id_to_structlog_context():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    request = _make_request()
    response = Response()
    captured_ctx = {}

    async def call_next(req):
        ctx = structlog.contextvars.get_contextvars()
        captured_ctx.update(ctx)
        return response

    await middleware.dispatch(request, call_next)
    assert "correlation_id" in captured_ctx
    assert len(captured_ctx["correlation_id"]) == 32


async def test_sets_sentry_tag_when_sdk_available():
    middleware = CorrelationIDMiddleware(app=MagicMock())
    request = _make_request()
    response = Response()

    with patch.dict("sys.modules", {"sentry_sdk": MagicMock()}) as modules:
        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)
        modules["sentry_sdk"].set_tag.assert_called_once()


async def test_gracefully_handles_missing_sentry():
    """No error when sentry_sdk is not installed."""
    middleware = CorrelationIDMiddleware(app=MagicMock())
    request = _make_request()
    response = Response()

    async def call_next(req):
        return response

    resp = await middleware.dispatch(request, call_next)
    assert CORRELATION_HEADER in resp.headers


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware
# ---------------------------------------------------------------------------

async def test_logs_request_info():
    middleware = RequestLoggingMiddleware(app=MagicMock())
    request = _make_request(headers={"user-agent": "TestAgent/1.0"})
    request.state.correlation_id = "abc-123"
    response = Response(status_code=200)

    async def call_next(req):
        return response

    with capture_logs() as cap_logs:
        await middleware.dispatch(request, call_next)

    assert len(cap_logs) == 1
    log = cap_logs[0]
    assert log["event"] == "GET /test"
    assert log["status"] == 200
    assert log["user"] == "anonymous"
    assert log["user_agent"] == "TestAgent/1.0"
    assert log["log_level"] == "info"
    assert "latency_ms" in log


async def test_logs_authenticated_user():
    middleware = RequestLoggingMiddleware(app=MagicMock())
    request = _make_request()
    request.state.correlation_id = "x"
    request.state.user_id = "user-456"
    response = Response(status_code=201)

    async def call_next(req):
        return response

    with capture_logs() as cap_logs:
        await middleware.dispatch(request, call_next)

    assert cap_logs[0]["user"] == "user-456"
    assert cap_logs[0]["status"] == 201


async def test_logs_latency_in_ms():
    middleware = RequestLoggingMiddleware(app=MagicMock())
    request = _make_request()
    request.state.correlation_id = "x"
    response = Response(status_code=200)

    async def call_next(req):
        return response

    with capture_logs() as cap_logs:
        await middleware.dispatch(request, call_next)

    assert isinstance(cap_logs[0]["latency_ms"], int)
    assert cap_logs[0]["latency_ms"] >= 0


async def test_handles_missing_correlation_id():
    """Logging middleware works even if correlation middleware didn't run."""
    middleware = RequestLoggingMiddleware(app=MagicMock())
    request = _make_request()
    response = Response(status_code=200)

    async def call_next(req):
        return response

    with capture_logs() as cap_logs:
        await middleware.dispatch(request, call_next)

    assert cap_logs[0]["event"] == "GET /test"


# ---------------------------------------------------------------------------
# APIKeyMiddleware
# ---------------------------------------------------------------------------

_TEST_KEY = "test-secret-key-abc123"


async def test_api_key_rejects_missing_header():
    with patch.object(settings, "api_key", _TEST_KEY):
        middleware = APIKeyMiddleware(app=MagicMock())
        request = _make_request()
        called = False

        async def call_next(req):
            nonlocal called
            called = True
            return Response()

        resp = await middleware.dispatch(request, call_next)
        assert not called
        assert resp.status_code == 403
        body = __import__("json").loads(resp.body)
        assert body["code"] == "FORBIDDEN"
        assert body["error"] == "Invalid or missing API key"


async def test_api_key_rejects_invalid_key():
    with patch.object(settings, "api_key", _TEST_KEY):
        middleware = APIKeyMiddleware(app=MagicMock())
        request = _make_request(headers={"x-api-key": "wrong-key"})
        called = False

        async def call_next(req):
            nonlocal called
            called = True
            return Response()

        resp = await middleware.dispatch(request, call_next)
        assert not called
        assert resp.status_code == 403


async def test_api_key_allows_valid_key():
    with patch.object(settings, "api_key", _TEST_KEY):
        middleware = APIKeyMiddleware(app=MagicMock())
        request = _make_request(headers={"x-api-key": _TEST_KEY})
        expected_response = Response(status_code=200)

        async def call_next(req):
            return expected_response

        resp = await middleware.dispatch(request, call_next)
        assert resp is expected_response


@pytest.mark.parametrize("path", list(_EXEMPT_PATHS))
async def test_api_key_skips_exempt_paths(path: str):
    with patch.object(settings, "api_key", _TEST_KEY):
        middleware = APIKeyMiddleware(app=MagicMock())
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
        request = Request(scope)
        expected_response = Response(status_code=200)

        async def call_next(req):
            return expected_response

        resp = await middleware.dispatch(request, call_next)
        assert resp is expected_response


async def test_api_key_skips_options_method():
    with patch.object(settings, "api_key", _TEST_KEY):
        middleware = APIKeyMiddleware(app=MagicMock())
        scope = {
            "type": "http",
            "method": "OPTIONS",
            "path": "/some-endpoint",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
        request = Request(scope)
        expected_response = Response(status_code=200)

        async def call_next(req):
            return expected_response

        resp = await middleware.dispatch(request, call_next)
        assert resp is expected_response


async def test_api_key_skips_when_not_configured():
    with patch.object(settings, "api_key", ""):
        middleware = APIKeyMiddleware(app=MagicMock())
        request = _make_request()
        expected_response = Response(status_code=200)

        async def call_next(req):
            return expected_response

        resp = await middleware.dispatch(request, call_next)
        assert resp is expected_response
