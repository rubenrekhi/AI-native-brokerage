from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_ssl_connect_args, settings

engine = create_async_engine(
    settings.database_url,
    # `statement_cache_size=0` disables asyncpg's per-connection prepared-
    # statement cache. Required when DATABASE_URL points at Supabase's
    # pgbouncer pool (transaction mode) because pgbouncer rotates server
    # connections per transaction, causing `DuplicatePreparedStatementError`
    # on any query after the first. Local dev is unaffected (no pooler).
    connect_args={
        **get_ssl_connect_args(settings.environment),
        "statement_cache_size": 0,
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
