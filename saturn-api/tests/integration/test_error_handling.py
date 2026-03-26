"""Integration tests — verify exception handlers are wired into the app."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from app.main import app


@pytest.fixture
async def client():
    mock_db = AsyncMock()

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    app.state.arq = AsyncMock(ping=AsyncMock(return_value=True))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_validation_error_format(client: AsyncClient):
    """POST to an endpoint that expects a body — omitting it triggers RequestValidationError."""
    # FastAPI's built-in validation fires when the request doesn't match.
    # We add a temporary route that requires a body param.
    from pydantic import BaseModel

    class Payload(BaseModel):
        name: str

    @app.post("/_test_validation")
    async def _test_route(payload: Payload):
        return {"ok": True}

    resp = await client.post("/_test_validation", content=b"{}")
    body = resp.json()

    assert resp.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert "fields" in body["detail"]

    # Clean up
    app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/_test_validation"]


async def test_http_exception_format(client: AsyncClient):
    from fastapi import HTTPException

    @app.get("/_test_http_exc")
    async def _raise():
        raise HTTPException(status_code=403, detail="Forbidden")

    resp = await client.get("/_test_http_exc")
    body = resp.json()

    assert resp.status_code == 403
    assert body["error"] == "Forbidden"
    assert body["code"] == "HTTP_ERROR"

    app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/_test_http_exc"]


async def test_custom_exception_format(client: AsyncClient):
    @app.get("/_test_not_found")
    async def _raise():
        raise NotFoundError("Item not found")

    resp = await client.get("/_test_not_found")
    body = resp.json()

    assert resp.status_code == 404
    assert body["code"] == "NOT_FOUND"
    assert body["error"] == "Item not found"

    app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/_test_not_found"]


async def test_authentication_error_format(client: AsyncClient):
    @app.get("/_test_auth")
    async def _raise():
        raise AuthenticationError("Invalid token")

    resp = await client.get("/_test_auth")
    body = resp.json()

    assert resp.status_code == 401
    assert body["code"] == "AUTHENTICATION_ERROR"
    assert body["error"] == "Invalid token"

    app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/_test_auth"]
