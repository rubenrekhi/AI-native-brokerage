"""Integration tests — verify middleware is wired into the app."""

import logging
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.middleware.correlation import CORRELATION_HEADER


@pytest.fixture
async def client():
    mock_db = AsyncMock()

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    app.state.arq = AsyncMock(ping=AsyncMock(return_value=True))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": settings.api_key},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------

async def test_response_contains_correlation_id(client: AsyncClient):
    resp = await client.get("/")
    assert CORRELATION_HEADER in resp.headers
    assert len(resp.headers[CORRELATION_HEADER]) == 32


async def test_echoes_provided_correlation_id(client: AsyncClient):
    custom_id = "my-custom-trace-id"
    resp = await client.get("/", headers={CORRELATION_HEADER: custom_id})
    assert resp.headers[CORRELATION_HEADER] == custom_id


async def test_different_requests_get_different_ids(client: AsyncClient):
    r1 = await client.get("/")
    r2 = await client.get("/")
    assert r1.headers[CORRELATION_HEADER] != r2.headers[CORRELATION_HEADER]


# ---------------------------------------------------------------------------
# Request logging
# ---------------------------------------------------------------------------

async def test_request_is_logged(client: AsyncClient, caplog):
    with caplog.at_level(logging.INFO, logger="saturn.access"):
        resp = await client.get("/")

    assert resp.status_code == 200
    access_records = [r for r in caplog.records if r.name == "saturn.access"]
    assert len(access_records) >= 1


async def test_health_endpoint_is_logged(client: AsyncClient, caplog):
    with caplog.at_level(logging.INFO, logger="saturn.access"):
        await client.get("/health")

    access_records = [r for r in caplog.records if r.name == "saturn.access"]
    assert len(access_records) >= 1


# ---------------------------------------------------------------------------
# API key gate
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_no_api_key():
    """Client without X-API-Key header for testing rejection."""
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


async def test_api_key_required_for_root(client_no_api_key: AsyncClient):
    resp = await client_no_api_key.get("/")
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "FORBIDDEN"
    assert body["error"] == "Invalid or missing API key"


async def test_api_key_valid_passes(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200


async def test_api_key_not_required_for_health(client_no_api_key: AsyncClient):
    resp = await client_no_api_key.get("/health")
    assert resp.status_code == 200
