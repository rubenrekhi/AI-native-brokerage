"""Integration tests — verify JWT auth dependency works end-to-end through the app."""

from unittest.mock import AsyncMock, patch

from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app

_TEST_PATH = "/_test_protected"


async def _setup_protected_route():
    """Add a temporary protected route for testing."""

    @app.get(_TEST_PATH)
    async def _protected(user_id: str = Depends(get_current_user)):
        return {"user_id": user_id}


async def _cleanup():
    app.routes[:] = [
        r for r in app.routes if getattr(r, "path", None) != _TEST_PATH
    ]
    app.dependency_overrides.clear()


async def _make_client() -> AsyncClient:
    mock_db = AsyncMock()

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    app.state.arq = AsyncMock(ping=AsyncMock(return_value=True))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# No token → 401
# ---------------------------------------------------------------------------


async def test_protected_route_without_token_returns_401():
    await _setup_protected_route()
    async with await _make_client() as client:
        resp = await client.get(_TEST_PATH)

    body = resp.json()
    assert resp.status_code == 401
    assert body["code"] == "AUTHENTICATION_ERROR"
    assert body["error"] == "Missing authorization header"

    await _cleanup()


# ---------------------------------------------------------------------------
# Invalid token → 401
# ---------------------------------------------------------------------------


async def test_protected_route_with_invalid_token_returns_401():
    await _setup_protected_route()
    async with await _make_client() as client:
        with patch("app.auth._jwks_client") as mock_jwks:
            from jwt.exceptions import PyJWKClientError

            mock_jwks.get_signing_key_from_jwt.side_effect = PyJWKClientError(
                "unable to find key"
            )
            resp = await client.get(
                _TEST_PATH, headers={"Authorization": "Bearer garbage-token"}
            )

    body = resp.json()
    assert resp.status_code == 401
    assert body["code"] == "AUTHENTICATION_ERROR"

    await _cleanup()


# ---------------------------------------------------------------------------
# Dependency override → 200
# ---------------------------------------------------------------------------


async def test_protected_route_with_override_returns_200():
    await _setup_protected_route()
    app.dependency_overrides[get_current_user] = lambda: "user-override-456"

    async with await _make_client() as client:
        resp = await client.get(_TEST_PATH)

    body = resp.json()
    assert resp.status_code == 200
    assert body["user_id"] == "user-override-456"

    await _cleanup()
