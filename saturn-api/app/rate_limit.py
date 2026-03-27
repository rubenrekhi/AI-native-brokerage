from starlette.requests import Request

from slowapi import Limiter

from app.config import settings


def get_user_or_ip(request: Request) -> str:
    """Key by authenticated user ID if available, otherwise by client IP."""
    try:
        user_id = request.state.user_id
        if user_id:
            return str(user_id)
    except AttributeError:
        pass
    return request.client.host if request.client else "unknown"


def get_remote_address(request: Request) -> str:
    """Key by client IP only — use for unauthenticated endpoints."""
    return request.client.host if request.client else "unknown"


limiter = Limiter(
    key_func=get_user_or_ip,
    default_limits=["120/minute"],
    storage_uri=settings.redis_url,
    enabled=True,
)
