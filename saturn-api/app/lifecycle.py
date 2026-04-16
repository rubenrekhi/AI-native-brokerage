from contextlib import asynccontextmanager
from arq.connections import create_pool
from fastapi import FastAPI
from app.config import get_redis_settings
from app.services.alpaca_broker import AlpacaBrokerService

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
    app.state.alpaca = AlpacaBrokerService()
    yield
    await app.state.alpaca.close()
    await app.state.arq.aclose()
