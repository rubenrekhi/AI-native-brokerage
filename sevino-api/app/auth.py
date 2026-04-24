import structlog
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, decode as jwt_decode
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.config import settings
from app.exceptions import AuthenticationError

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_jwks_client = PyJWKClient(
    f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Extract and verify the Supabase JWT from the Authorization header.

    Returns the user ID (``sub`` claim) on success, raises
    ``AuthenticationError`` on any failure.
    """
    if credentials is None:
        raise AuthenticationError("Missing authorization header")

    token = credentials.credentials

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
    except (PyJWKClientError, InvalidTokenError) as exc:
        logger.warning("jwks_key_fetch_failed", error=str(exc))
        raise AuthenticationError("Unable to verify token")

    try:
        payload = jwt_decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except InvalidTokenError as exc:
        logger.warning("jwt_verification_failed", error=str(exc))
        raise AuthenticationError("Invalid or expired token")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Token missing subject claim")

    request.state.user_id = user_id
    return user_id


async def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Return the raw Bearer token string.

    Pair with ``get_current_user`` on handlers that need to forward the
    caller's JWT to another service (e.g. Supabase GoTrue).
    """
    if credentials is None:
        raise AuthenticationError("Missing authorization header")
    return credentials.credentials
