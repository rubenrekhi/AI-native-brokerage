from contextlib import asynccontextmanager
from urllib.parse import urlparse, urlunparse

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
from app.services.market_data import MarketDataService
from app.services.phone_verification import PhoneVerificationService
from app.services.plaid import PlaidService
from app.services.supabase_admin import SupabaseAdminService


def _swap_redis_db(url: str, db: int) -> str:
    """Force a Redis URL onto the given db index.

    `Redis.from_url(url, db=N)` does NOT override the URL's path-encoded
    db, so we rewrite the URL itself. Any existing db path component is
    overwritten unconditionally — the caller decides which db to use.
    """
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{db}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.arq = await create_pool(get_redis_settings())
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
        app.state.market_data_redis = Redis.from_url(
            _swap_redis_db(settings.redis_url, 1)
        )
        app.state.market_data = MarketDataService(
            fmp=FmpClient(api_key=settings.fmp_api_key),
            alpaca_broker=app.state.alpaca,
            redis=app.state.market_data_redis,
            alpaca_data_url=settings.alpaca_data_base_url,
            alpaca_broker_url=settings.alpaca_base_url,
        )
    else:
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
    await app.state.arq.aclose()
