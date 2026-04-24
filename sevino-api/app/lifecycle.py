from contextlib import asynccontextmanager
from arq.connections import create_pool
from fastapi import FastAPI
from app.config import get_redis_settings
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
    yield
    await app.state.supabase_admin.close()
    await app.state.phone_verification.close()
    app.state.plaid.close()
    await app.state.alpaca.close()
    await app.state.arq.aclose()
