from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_db
from app.main import app

TEST_API_KEY = "test-api-key-for-testing"
settings.api_key = TEST_API_KEY


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def mock_arq():
    pool = AsyncMock()
    pool.ping = AsyncMock(return_value=True)
    return pool


@pytest.fixture
async def client(mock_db, mock_arq):
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


@pytest.fixture
def mock_current_user():
    """Fixed user ID returned by the auth dependency override."""
    return "test-user-id-123"


@pytest.fixture
async def authenticated_client(mock_db, mock_arq, mock_current_user):
    """AsyncClient with auth dependency overridden to return mock_current_user."""
    from app.auth import get_current_user

    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    app.state.arq = mock_arq

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
