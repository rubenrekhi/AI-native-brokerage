import hmac

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.exceptions import error_response

logger = structlog.get_logger(__name__)

_EXEMPT_PATHS = frozenset(
    {"/health", "/docs", "/redoc", "/openapi.json", "/v1/plaid/webhooks"}
)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Lightweight gate that rejects requests without a valid X-API-Key header.

    Skipped entirely when ``settings.api_key`` is not configured (empty string),
    and always skipped for health/docs endpoints and CORS preflight requests.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not settings.api_key:
            return await call_next(request)

        if request.url.path in _EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        api_key = request.headers.get("x-api-key", "")

        if not api_key or not hmac.compare_digest(api_key, settings.api_key):
            logger.warning(
                "api_key_rejected",
                path=request.url.path,
                reason="missing" if not api_key else "invalid",
            )
            return error_response(403, "Invalid or missing API key", "FORBIDDEN")

        return await call_next(request)
