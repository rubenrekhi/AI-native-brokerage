"""Plaid webhook signature verification.

Plaid signs every webhook with an ES256 JWT in the `Plaid-Verification` header.
The JWT carries a SHA-256 hash of the raw request body plus an `iat` claim;
we require `iat` to be within +/- 5 minutes of now (Plaid's documented replay
window). Verification keys rotate; we cache JWKs by `kid` and reject any
JWK whose `expired_at` has passed.

Reference: https://plaid.com/docs/api/webhooks/webhook-verification/

Raises `PlaidServiceError("WEBHOOK_INVALID_SIGNATURE", status_code=401)` on
any verification failure. The global handler maps `PlaidServiceError` to 422;
callers that need 401 must catch and re-raise.
"""

import hashlib
import hmac
import time
from typing import Any

import jwt
import structlog
from jwt import PyJWK
from jwt.exceptions import InvalidTokenError

from app.services.plaid import PlaidService, PlaidServiceError

logger = structlog.get_logger(__name__)

_MAX_IAT_SKEW_SECONDS = 5 * 60

_jwk_cache: dict[str, dict[str, Any]] = {}


def _invalid(reason: str) -> PlaidServiceError:
    logger.warning("plaid_webhook_signature_failed", reason=reason)
    return PlaidServiceError(
        code="WEBHOOK_INVALID_SIGNATURE",
        message=reason,
        status_code=401,
    )


def _check_not_expired(jwk_dict: dict[str, Any]) -> None:
    expired_at = jwk_dict.get("expired_at")
    if expired_at is not None and expired_at < time.time():
        raise _invalid("Signing key has been rotated out")


async def verify_webhook(
    plaid: PlaidService,
    *,
    raw_body: bytes,
    signature_header: str | None,
) -> None:
    if not signature_header:
        raise _invalid("Missing Plaid-Verification header")

    try:
        unverified_header = jwt.get_unverified_header(signature_header)
    except InvalidTokenError as exc:
        raise _invalid("Malformed JWT header") from exc

    if unverified_header.get("alg") != "ES256":
        raise _invalid("Unexpected JWT alg")

    kid = unverified_header.get("kid")
    if not kid:
        raise _invalid("Missing kid in JWT header")

    jwk_dict = _jwk_cache.get(kid)
    if jwk_dict is None:
        try:
            jwk_dict = await plaid.get_webhook_verification_key(kid)
        except PlaidServiceError as exc:
            raise _invalid("Failed to fetch signing key") from exc
        _check_not_expired(jwk_dict)
        _jwk_cache[kid] = jwk_dict
    else:
        _check_not_expired(jwk_dict)

    try:
        claims = jwt.decode(
            signature_header,
            PyJWK(jwk_dict).key,
            algorithms=["ES256"],
            options={"verify_iat": False},
        )
    except InvalidTokenError as exc:
        raise _invalid("JWT signature verification failed") from exc

    iat = claims.get("iat", 0)
    now = time.time()
    if not (now - _MAX_IAT_SKEW_SECONDS <= iat <= now + _MAX_IAT_SKEW_SECONDS):
        raise _invalid("Webhook iat outside 5-minute replay window")

    expected_hash = hashlib.sha256(raw_body).hexdigest()
    received_hash = claims.get("request_body_sha256", "")
    if not hmac.compare_digest(expected_hash, received_hash):
        raise _invalid("Webhook body hash mismatch")


def _reset_jwk_cache() -> None:
    """Test-only cache reset. Production never invalidates."""
    _jwk_cache.clear()
