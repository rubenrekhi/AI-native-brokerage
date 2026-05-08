"""Smoke harness for the chat-turn endpoint.

Spins up a real uvicorn server bound to localhost, hits
``POST /v1/conversations/{id}/turns`` over HTTP, and parses the SSE
stream into typed events. Default-skipped via ``collect_ignore_glob``
so ``make test`` does not collect this directory; opt in with
``RUN_AI_SMOKE=1``.

Per AI v0 plan B4.1 (``sevino-api/docs/ai-v0-plan.md``).

Prerequisites for an enabled run:

* ``make infra`` (Supabase Postgres on :54322 + Redis on :6379)
* Real ``ANTHROPIC_API_KEY`` in ``.env`` — smoke tests bill Anthropic
* All other env vars required by ``app.config.Settings``

The fixtures (``smoke_server``, ``smoke_user``, ``smoke_client``,
``smoke_conversation_id``) plus the SSE helper ``parse_sse_event`` are
consumed by the per-case smoke tests landing in B4.2 / B4.3 / C5.3.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator

# Default-skip the entire directory unless RUN_AI_SMOKE=1 is set so that
# ``make test`` (and any other plain pytest run) does not collect or run
# anything here. Tests under this directory are intentionally costly —
# real Anthropic calls, real local stack — and must be opted into.
if os.environ.get("RUN_AI_SMOKE") != "1":
    collect_ignore_glob = ["test_*.py"]

import httpx
import httpx_sse
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.transport.events import Event, parse_wire_frame
from app.auth import get_current_user
from app.config import settings
from app.main import app
from tests.integration.conftest import (  # noqa: F401 — db_engine re-exported
    DB_URL,
    _pg_available_sync,
    db_engine,
    insert_auth_user,
)


@pytest.fixture(scope="session", autouse=True)
def _smoke_prereqs() -> None:
    """Skip the suite cleanly when prerequisites are missing.

    ``RUN_AI_SMOKE=1`` is a coarse opt-in. The fixture verifies the
    environmental prerequisites that opting in implies: a reachable
    local Postgres and a real Anthropic key. When either is missing we
    want a loud skip with an actionable reason, not a connection error
    or 401 deep inside the agent loop.
    """
    if not _pg_available_sync:
        pytest.skip(
            "Local Supabase Postgres not available (run `make infra`)"
        )
    key = (settings.anthropic_api_key or "").strip()
    if not key or key.startswith(("ci-", "test-")):
        pytest.skip(
            "ANTHROPIC_API_KEY must be set to a real key for smoke tests"
        )


# --- server lifecycle ------------------------------------------------------


def _free_tcp_port() -> int:
    """Pick an ephemeral port on loopback. The bind/release/rebind window
    is tiny but real — acceptable for local and CI smoke runs, where
    nothing else is fighting for ports."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def smoke_server() -> Iterator[str]:
    """Start a uvicorn server on a free port; yield its base URL.

    The server runs in a background thread inside the same Python
    process as the tests so that mutating ``app.dependency_overrides``
    (e.g. swapping ``get_current_user`` per test) is visible to the
    server's request handlers without having to round-trip through
    environment variables.
    """
    port = _free_tcp_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(
        target=server.run, name="smoke-uvicorn", daemon=True
    )
    thread.start()

    deadline = time.monotonic() + 30.0
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("smoke server failed to start within 30s")
        time.sleep(0.05)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


# --- per-test fixtures -----------------------------------------------------


@pytest.fixture
async def smoke_user() -> AsyncIterator[uuid.UUID]:
    """Insert a fresh user, install ``get_current_user`` override, then
    delete the user's full turn graph at teardown.

    The smoke server uses the lifespan-bound session factory, which
    commits per-write — the rolling-back ``db_session`` fixture from
    ``tests/integration/conftest.py`` cannot reach those rows, so
    cleanup is managed here in the FK-safe order used by
    ``tests/ai/integration/test_loop_persistence.py``.

    A short-lived engine is used rather than the session-scoped
    ``db_engine`` so that a stuck smoke run cannot tie up the shared
    connection across the rest of the session.
    """
    user_id = uuid.uuid4()
    email = f"smoke-{user_id}@test.local"
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with AsyncSession(bind=engine, expire_on_commit=False) as setup:
            await insert_auth_user(setup, user_id=user_id, email=email)
            await setup.commit()

        app.dependency_overrides[get_current_user] = lambda: str(user_id)
        try:
            yield user_id
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            await _cleanup_user(engine, user_id)
    finally:
        await engine.dispose()


async def _cleanup_user(engine, user_id: uuid.UUID) -> None:
    """Delete every row anchored to ``user_id`` in FK-safe order.

    The smoke server creates conversation rows implicitly on first turn
    (decision D6), so conversation IDs aren't known ahead of time —
    cleanup is scoped by ``user_id`` instead.
    """
    async with AsyncSession(bind=engine, expire_on_commit=False) as cleanup:
        await cleanup.execute(
            text(
                "DELETE FROM tool_executions WHERE model_invocation_id IN ("
                "SELECT mi.id FROM model_invocations mi "
                "JOIN agent_turns at ON mi.agent_turn_id = at.id "
                "JOIN conversations c ON at.conversation_id = c.id "
                "WHERE c.user_id = :uid)"
            ),
            {"uid": user_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM model_invocations WHERE agent_turn_id IN ("
                "SELECT at.id FROM agent_turns at "
                "JOIN conversations c ON at.conversation_id = c.id "
                "WHERE c.user_id = :uid)"
            ),
            {"uid": user_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM agent_turns WHERE conversation_id IN ("
                "SELECT id FROM conversations WHERE user_id = :uid)"
            ),
            {"uid": user_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM messages WHERE conversation_id IN ("
                "SELECT id FROM conversations WHERE user_id = :uid)"
            ),
            {"uid": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM conversations WHERE user_id = :uid"),
            {"uid": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM user_profiles WHERE id = :uid"),
            {"uid": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM auth.users WHERE id = :uid"),
            {"uid": user_id},
        )
        await cleanup.commit()


@pytest.fixture
def smoke_conversation_id() -> uuid.UUID:
    """Fresh conversation UUID per test. The server creates the row
    implicitly on the first turn (decision D6)."""
    return uuid.uuid4()


@pytest.fixture
async def smoke_client(smoke_server: str) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client bound to the smoke server with API-key auth prefilled.

    Read timeout is generous because real Anthropic streams typically
    take 5-30s; ``httpx_sse.aconnect_sse`` inherits this timeout when
    used against the same client.
    """
    headers: dict[str, str] = {}
    if settings.api_key:
        headers["X-API-Key"] = settings.api_key

    async with httpx.AsyncClient(
        base_url=smoke_server,
        headers=headers,
        timeout=httpx.Timeout(60.0, read=60.0),
    ) as client:
        yield client


# --- SSE parser helper -----------------------------------------------------


def parse_sse_event(sse: httpx_sse.ServerSentEvent) -> Event:
    """Convert an ``httpx_sse.ServerSentEvent`` into a typed agent
    :class:`Event`.

    Reconstructs the wire frame and feeds it through
    :func:`parse_wire_frame` so the cross-validation between the SSE
    ``id:`` / ``event:`` lines and the JSON body runs end-to-end in
    smoke tests too — a wire-format regression in the server should
    fail loudly here, not paper over.
    """
    parts: list[str] = []
    if sse.id:
        parts.append(f"id: {sse.id}")
    if sse.event:
        parts.append(f"event: {sse.event}")
    parts.append(f"data: {sse.data}")
    return parse_wire_frame("\n".join(parts) + "\n")
