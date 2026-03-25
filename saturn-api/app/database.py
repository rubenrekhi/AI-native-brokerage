from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_ssl_connect_args, settings

engine = create_async_engine(
    settings.database_url,
    connect_args=get_ssl_connect_args(settings.environment),
)

async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
