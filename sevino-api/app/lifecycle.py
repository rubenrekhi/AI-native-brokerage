from contextlib import asynccontextmanager
from arq.connections import create_pool
from fastapi import FastAPI
from app.ai.anthropic_client import create_anthropic_client
from app.ai.observability.langfuse import create_langfuse_client
from app.ai.runtime.db import make_session_factory
from app.config import get_redis_settings, settings
from app.database import engine
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.phone_verification import PhoneVerificationService
from app.services.plaid import PlaidService
from app.services.supabase_admin import SupabaseAdminService

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
    yield
    app.state.langfuse.shutdown()
    await app.state.anthropic.close()
    await app.state.supabase_admin.close()
    await app.state.phone_verification.close()
    app.state.plaid.close()
    await app.state.alpaca.close()
    await app.state.arq.aclose()
