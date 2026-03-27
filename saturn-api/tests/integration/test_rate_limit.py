"""Integration tests for rate limiting.

These tests re-enable the limiter (disabled globally in conftest.py) with a
tight in-memory limit so we can trigger a 429 without needing Redis.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.rate_limit import limiter
from tests.conftest import TEST_API_KEY


@pytest.fixture(autouse=True)
def _enable_limiter():
    """Re-enable the limiter for this module's tests, then restore."""
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False


@pytest.fixture
async def rate_limit_client(mock_db, mock_arq):
    """Client whose requests count against the rate limiter."""
    from app.database import get_db

    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.state.arq = mock_arq

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


async def test_rate_limit_returns_structured_429(rate_limit_client: AsyncClient):
    """After exceeding the default 120/minute limit, the response is a structured 429."""
    # Exhaust the default 120/minute limit on /health/auth (not exempt).
    for _ in range(120):
        resp = await rate_limit_client.get("/health/auth")
        # /health/auth requires auth; 401 is expected, but it still counts.
        assert resp.status_code in (200, 401)

    # The 121st request should be rate-limited.
    resp = await rate_limit_client.get("/health/auth")
    assert resp.status_code == 429
    body = resp.json()
    assert body["error"] == "Rate limit exceeded"
    assert body["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in resp.headers


async def test_health_endpoint_exempt_from_rate_limit(rate_limit_client: AsyncClient):
    """The /health endpoint should never return 429, even after many requests."""
    for _ in range(150):
        resp = await rate_limit_client.get("/health")
        assert resp.status_code != 429
