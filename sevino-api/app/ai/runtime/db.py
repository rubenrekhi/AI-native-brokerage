"""Session-per-write factory for the agent runtime.

The loop doesn't use ``Depends(get_db)`` — a request-scoped session held
across a 60s streaming turn is unsafe under pgbouncer transaction-mode
(it can silently rebind the connection mid-flight). Audit rows also need
to be durable mid-turn, not batched at the end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

DbSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def get_db_factory(request: Request) -> DbSessionFactory:
    return request.app.state.db_factory


def make_session_factory(engine: AsyncEngine) -> DbSessionFactory:
    """Build a session-per-write factory bound to ``engine``.

    Pattern::

        async with db_factory() as db:
            await ConversationRepository.append_user_message(db, ...)
    """
    # ``expire_on_commit=False`` so freshly-flushed instances stay
    # attribute-accessible after the context exits.
    maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return factory
