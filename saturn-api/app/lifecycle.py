from contextlib import asynccontextmanager
from arq.connections import create_pool
from fastapi import FastAPI
from app.config import get_redis_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
    yield
    await app.state.arq.aclose()
