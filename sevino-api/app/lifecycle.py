from contextlib import asynccontextmanager

from arq.connections import create_pool
from fastapi import FastAPI
from redis.asyncio import Redis

from app.ai.anthropic_client import create_anthropic_client
from app.ai.observability.langfuse import create_langfuse_client
from app.ai.runtime.db import make_session_factory
from app.config import get_redis_settings, settings
from app.database import engine
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.fmp import FmpClient
from app.services.market_data import build_market_data_service
from app.services.phone_verification import PhoneVerificationService
from app.services.plaid import PlaidService
from app.services.supabase_admin import SupabaseAdminService


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
    app.state.redis = Redis.from_url(
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
    app.state.db_factory = make_session_factory(engine)
    # MarketDataService gets its own Redis client on db=1 so a market-data
    # cache flush can't wipe ARQ job state, and its own FmpClient so the
    # boundary stays self-contained. Skip in dev when FMP_API_KEY is missing
    # so unrelated workflows (onboarding, trading) still boot.
    if settings.fmp_api_key:
        app.state.fmp = FmpClient(api_key=settings.fmp_api_key)
        app.state.market_data_redis = Redis.from_url(settings.market_data_redis_url)
        app.state.market_data = build_market_data_service(
            fmp=app.state.fmp,
            alpaca_broker=app.state.alpaca,
            redis=app.state.market_data_redis,
        )
    else:
        app.state.fmp = None
        app.state.market_data_redis = None
        app.state.market_data = None
    yield
    if app.state.market_data is not None:
        await app.state.market_data.close()
    if app.state.market_data_redis is not None:
        await app.state.market_data_redis.aclose()
    app.state.langfuse.shutdown()
    await app.state.anthropic.close()
    await app.state.supabase_admin.close()
    await app.state.phone_verification.close()
    app.state.plaid.close()
    await app.state.alpaca.close()
    await app.state.redis.aclose()
    await app.state.arq.aclose()
