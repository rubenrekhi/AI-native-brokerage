from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from arq.connections import create_pool
from fastapi import FastAPI

from app.config import get_redis_settings, settings
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.plaid import PlaidService

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
    app.state.redis = aioredis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        encoding="utf-8",
    )
    logger.info("redis client ready")
    app.state.alpaca = AlpacaBrokerService()
    app.state.plaid = PlaidService()
    yield
    app.state.plaid.close()
    await app.state.alpaca.close()
    await app.state.redis.aclose()
    await app.state.arq.aclose()
