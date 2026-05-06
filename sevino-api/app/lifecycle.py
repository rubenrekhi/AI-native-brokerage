from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq.connections import create_pool
from fastapi import FastAPI

from app.ai.anthropic_client import create_anthropic_client
from app.ai.observability.langfuse import create_langfuse_client
from app.config import get_redis_settings, settings
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.phone_verification import PhoneVerificationService
from app.services.plaid import PlaidService
from app.services.supabase_admin import SupabaseAdminService


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
    app.state.alpaca = AlpacaBrokerService()
    app.state.plaid = PlaidService()
    app.state.phone_verification = PhoneVerificationService()
    app.state.supabase_admin = SupabaseAdminService()
    app.state.anthropic = create_anthropic_client()
    app.state.langfuse = create_langfuse_client(settings)
    yield
    app.state.langfuse.shutdown()
    await app.state.anthropic.close()
    await app.state.supabase_admin.close()
    await app.state.phone_verification.close()
    app.state.plaid.close()
    await app.state.alpaca.close()
    await app.state.redis.aclose()
    await app.state.arq.aclose()
