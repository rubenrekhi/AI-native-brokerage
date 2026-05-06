"""Session-per-write factory for the agent runtime.

Per AI v0 plan decision D12 (sevino-api/docs/ai-v0-plan.md): the agent loop
must NOT use ``Depends(get_db)``. The request-scoped session would hold a
single asyncpg connection across the full streaming turn (~60s), which is
unsafe under Supabase's pgbouncer transaction-mode pool — pgbouncer can
silently rebind a returned connection mid-flight. The spec also requires
audit rows (``model_invocations``) to be durable mid-turn, not batched
until the turn ends.

Solution: each repository call inside the loop opens a fresh
``AsyncSession``, commits, closes via the factory returned here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

DbSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def make_session_factory(engine: AsyncEngine) -> DbSessionFactory:
    """Build a session-per-write factory bound to ``engine``.

    Returned callable opens a fresh ``AsyncSession`` on every call. Caller
    pattern::

        async with db_factory() as db:
            await ConversationRepository.append_user_message(db, ...)
        # auto-commit on context exit; rollback on exception

    Sessions use ``expire_on_commit=False`` so freshly-flushed model
    instances stay attribute-accessible after the context exits — callers
    typically need ``user_message.id`` after the commit.
    """
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
