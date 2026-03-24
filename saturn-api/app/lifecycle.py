from contextlib import asynccontextmanager
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from app.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await app.state.arq.aclose()
