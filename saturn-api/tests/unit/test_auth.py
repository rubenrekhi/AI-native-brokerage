"""Unit tests for app.auth — get_current_user dependency."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidSignatureError,
    PyJWKClientError,
)
from starlette.datastructures import State
from starlette.requests import Request

from app.auth import get_current_user
from app.exceptions import AuthenticationError


def _creds(token: str = "fake-token") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _request() -> Request:
    """Build a minimal Starlette Request with a mutable state."""
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    req = Request(scope)
    req._state = State()
    return req


# ---------------------------------------------------------------------------
# Missing / absent credentials
# ---------------------------------------------------------------------------


async def test_missing_credentials_raises_authentication_error():
    with pytest.raises(AuthenticationError, match="Missing authorization header"):
        await get_current_user(request=_request(), credentials=None)


# ---------------------------------------------------------------------------
# JWKS fetch failures
# ---------------------------------------------------------------------------


async def test_jwks_fetch_failure_raises_authentication_error():
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        pytest.raises(AuthenticationError, match="Unable to verify token"),
    ):
        mock_jwks.get_signing_key_from_jwt.side_effect = PyJWKClientError(
            "Connection refused"
        )
        await get_current_user(request=_request(), credentials=_creds())


async def test_malformed_token_raises_authentication_error():
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        pytest.raises(AuthenticationError, match="Unable to verify token"),
    ):
        mock_jwks.get_signing_key_from_jwt.side_effect = DecodeError(
            "Invalid payload string"
        )
        await get_current_user(request=_request(), credentials=_creds())


# ---------------------------------------------------------------------------
# Token verification failures
# ---------------------------------------------------------------------------


async def test_expired_token_raises_authentication_error():
    mock_key = MagicMock()
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        patch("app.auth.jwt_decode", side_effect=ExpiredSignatureError("expired")),
        pytest.raises(AuthenticationError, match="Invalid or expired token"),
    ):
        mock_jwks.get_signing_key_from_jwt.return_value = mock_key
        await get_current_user(request=_request(), credentials=_creds())


async def test_invalid_signature_raises_authentication_error():
    mock_key = MagicMock()
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        patch("app.auth.jwt_decode", side_effect=InvalidSignatureError("bad sig")),
        pytest.raises(AuthenticationError, match="Invalid or expired token"),
    ):
        mock_jwks.get_signing_key_from_jwt.return_value = mock_key
        await get_current_user(request=_request(), credentials=_creds())


# ---------------------------------------------------------------------------
# Missing sub claim
# ---------------------------------------------------------------------------


async def test_missing_sub_claim_raises_authentication_error():
    mock_key = MagicMock()
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        patch("app.auth.jwt_decode", return_value={"exp": 9999999999, "sub": ""}),
        pytest.raises(AuthenticationError, match="Token missing subject claim"),
    ):
        mock_jwks.get_signing_key_from_jwt.return_value = mock_key
        await get_current_user(request=_request(), credentials=_creds())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_valid_token_returns_user_id():
    mock_key = MagicMock()
    req = _request()
    with (
        patch("app.auth._jwks_client") as mock_jwks,
        patch(
            "app.auth.jwt_decode",
            return_value={"exp": 9999999999, "sub": "user-abc-123"},
        ),
    ):
        mock_jwks.get_signing_key_from_jwt.return_value = mock_key
        result = await get_current_user(request=req, credentials=_creds())

    assert result == "user-abc-123"
    assert req.state.user_id == "user-abc-123"
