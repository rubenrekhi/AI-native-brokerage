from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from arq.connections import create_pool
from fastapi import FastAPI

from app.config import get_redis_settings, settings
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.phone_verification import PhoneVerificationService
from app.services.plaid import PlaidService
from app.services.supabase_admin import SupabaseAdminService

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
    app.state.redis = aioredis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        encoding="utf-8",
    )
    try:
        await app.state.redis.ping()
    except Exception:
        await app.state.redis.aclose()
        await app.state.arq.aclose()
        raise
    logger.info("redis client ready")
    app.state.alpaca = AlpacaBrokerService()
    app.state.plaid = PlaidService()
    app.state.phone_verification = PhoneVerificationService()
    app.state.supabase_admin = SupabaseAdminService()
    yield
    try:
        await app.state.supabase_admin.close()
    except Exception:
        logger.exception("supabase_admin close failed")
    try:
        await app.state.phone_verification.close()
    except Exception:
        logger.exception("phone_verification close failed")
    try:
        app.state.plaid.close()
    except Exception:
        logger.exception("plaid close failed")
    try:
        await app.state.alpaca.close()
    except Exception:
        logger.exception("alpaca close failed")
    try:
        await app.state.redis.aclose()
    except Exception:
        logger.exception("redis close failed")
    try:
        await app.state.arq.aclose()
    except Exception:
        logger.exception("arq close failed")
