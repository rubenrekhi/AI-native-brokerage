import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger("saturn.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, user, status, latency,
    correlation ID, client IP, and User-Agent.

    The correlation ID is automatically included via structlog contextvars
    (bound by CorrelationIDMiddleware).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000)

        user_id = getattr(request.state, "user_id", None) or "anonymous"
        client_ip = request.client.host if request.client else "-"
        user_agent = request.headers.get("user-agent", "-")

        logger.info(
            request.method + " " + request.url.path,
            status=response.status_code,
            user=user_id,
            latency_ms=latency_ms,
            ip=client_ip,
            user_agent=user_agent,
        )
        return response
