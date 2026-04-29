"""
Integration test fixtures using real local Supabase Postgres.

Requires: Docker running + `make infra` (Supabase on localhost:54322).
Tests using these fixtures are skipped automatically if Postgres is unavailable.
"""

import asyncio
import uuid

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.main import app
from app.rate_limit import limiter

TEST_API_KEY = "test-api-key-for-testing"
TEST_USER_ID = str(uuid.uuid4())
TEST_USER_EMAIL = "testuser@example.com"

DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:54322/postgres"

limiter.enabled = False
settings.api_key = TEST_API_KEY


async def _pg_available() -> bool:
    """Check if local Postgres is accepting connections."""
    try:
        conn = await asyncpg.connect(
            host="localhost", port=54322, user="postgres", password="postgres", database="postgres"
        )
        await conn.close()
        return True
    except (OSError, asyncpg.PostgresError):
        return False


# Check availability once at import time for the skip marker
try:
    _pg_available_sync = asyncio.new_event_loop().run_until_complete(_pg_available())
except Exception:
    _pg_available_sync = False


async def insert_auth_user(
    session: AsyncSession, *, user_id: uuid.UUID, email: str
) -> None:
    """Insert a row into ``auth.users`` (and matching ``user_profiles``) so
    integration tests can satisfy FKs without going through Supabase auth.

    Reused by ``test_user`` and by tests that need to commit a user outside
    the rolling-back ``db_session`` (e.g. cross-session concurrency tests).
    """
    await session.execute(
        text("""
            INSERT INTO auth.users (
                id, instance_id, email, encrypted_password,
                aud, role, raw_app_meta_data, raw_user_meta_data,
                created_at, updated_at, confirmation_token, email_change,
                email_change_token_new, recovery_token
            ) VALUES (
                :id, '00000000-0000-0000-0000-000000000000', :email, '',
                'authenticated', 'authenticated', '{}', '{}',
                now(), now(), '', '', '', ''
            )
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": user_id, "email": email},
    )
    await session.execute(
        text("""
            INSERT INTO user_profiles (id, email, created_at, updated_at)
            VALUES (:id, :email, now(), now())
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": user_id, "email": email},
    )


@pytest.fixture(scope="session")
def db_engine():
    """Create a single engine for the entire test session."""
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    yield engine


@pytest.fixture
async def db_session(db_engine):
    """
    Provide a real DB session that rolls back after each test.

    The session is created directly from the engine. The get_db override
    yields this session without committing. After the test, everything
    is rolled back — no data persists between tests.

    Flushed data is visible within the same session (same connection),
    so test assertions can query the DB via this session and see writes
    made by the endpoint.
    """
    session = AsyncSession(bind=db_engine, expire_on_commit=False)

    async def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db

    yield session

    await session.rollback()
    await session.close()
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """
    Insert a test user into auth.users and user_profiles.

    Mimics what happens in production: Supabase creates auth.users,
    the trigger creates user_profiles. In tests we do both manually.
    Rolled back with the session after the test.
    """
    user_id = uuid.UUID(TEST_USER_ID)
    await insert_auth_user(db_session, user_id=user_id, email=TEST_USER_EMAIL)
    await db_session.flush()
    return user_id


@pytest.fixture
async def authenticated_db_client(db_session, test_user):
    """
    AsyncClient with real DB session and mocked auth.
    The user returned by get_current_user matches the test_user in the DB.
    """
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_current_user, None)
