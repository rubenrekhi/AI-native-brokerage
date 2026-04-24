from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_ssl_connect_args, settings

engine = create_async_engine(
    settings.database_url,
    # NullPool: don't hold idle connections across checkouts. Required when
    # DATABASE_URL points at Supabase's pgbouncer pool (transaction mode)
    # because pgbouncer may silently rebind a returned connection to a
    # different Postgres backend.
    poolclass=NullPool,
    connect_args={
        **get_ssl_connect_args(settings.environment),
        # Disable asyncpg's per-connection prepared-statement cache.
        "statement_cache_size": 0,
        # Disable SQLAlchemy asyncpg dialect's own prepared-statement cache
        # (the layer that produces "__asyncpg_stmt_N__" names).
        "prepared_statement_cache_size": 0,
    },
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
