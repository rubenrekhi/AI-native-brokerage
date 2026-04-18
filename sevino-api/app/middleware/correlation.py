import uuid

from structlog.contextvars import bind_contextvars, clear_contextvars
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Assign a correlation ID to every request for end-to-end tracing.

    * Reuses an incoming ``X-Correlation-ID`` header when present.
    * Otherwise generates a new UUID4.
    * Stores the ID on ``request.state.correlation_id``.
    * Binds it to structlog contextvars (appears in all downstream logs).
    * Echoes it back as a response header.
    * Attaches it to the Sentry scope (when sentry-sdk is installed).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_HEADER) or uuid.uuid4().hex
        request.state.correlation_id = correlation_id

        clear_contextvars()
        bind_contextvars(correlation_id=correlation_id)

        self._set_sentry_context(correlation_id)

        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @staticmethod
    def _set_sentry_context(correlation_id: str) -> None:
        try:
            import sentry_sdk

            sentry_sdk.set_tag("correlation_id", correlation_id)
        except ImportError:
            pass
