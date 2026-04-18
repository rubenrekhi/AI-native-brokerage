"""Integration tests — verify JWT auth dependency works end-to-end through the app."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.auth import get_current_user
from app.config import settings
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
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": settings.api_key},
    )


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


# ---------------------------------------------------------------------------
# API key + JWT interaction on /health/auth
# ---------------------------------------------------------------------------


async def _make_bare_client() -> AsyncClient:
    """Client with no default auth headers."""
    mock_db = AsyncMock()
    mock_row = MagicMock()
    mock_row.email = "test@example.com"
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = mock_row
    mock_db.execute.return_value = mock_result

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    app.state.arq = AsyncMock(ping=AsyncMock(return_value=True))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_auth_with_api_key_and_token_returns_200():
    app.dependency_overrides[get_current_user] = lambda: "user-789"
    async with await _make_bare_client() as client:
        resp = await client.get(
            "/health/auth",
            headers={"X-API-Key": settings.api_key},
        )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "user-789"
    app.dependency_overrides.clear()


async def test_health_auth_with_api_key_only_returns_401():
    async with await _make_bare_client() as client:
        resp = await client.get(
            "/health/auth",
            headers={"X-API-Key": settings.api_key},
        )
    body = resp.json()
    assert resp.status_code == 401
    assert body["code"] == "AUTHENTICATION_ERROR"
    app.dependency_overrides.clear()


async def test_health_auth_with_bearer_only_returns_403():
    async with await _make_bare_client() as client:
        resp = await client.get(
            "/health/auth",
            headers={"Authorization": "Bearer some-token"},
        )
    body = resp.json()
    assert resp.status_code == 403
    assert body["code"] == "FORBIDDEN"
    app.dependency_overrides.clear()


async def test_health_auth_with_neither_returns_403():
    async with await _make_bare_client() as client:
        resp = await client.get("/health/auth")
    body = resp.json()
    assert resp.status_code == 403
    assert body["code"] == "FORBIDDEN"
    app.dependency_overrides.clear()
