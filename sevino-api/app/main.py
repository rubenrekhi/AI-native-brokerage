from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import sentry_sdk
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.sentry_config import before_send as sentry_before_send
from app.database import get_db
from app.exceptions import error_response, register_exception_handlers
from app.lifecycle import lifespan
from app.logging_config import configure_logging
from app.middleware import APIKeyMiddleware, CorrelationIDMiddleware, RequestLoggingMiddleware
from app.rate_limit import limiter
from app.routes.admin_radar import router as admin_radar_router
from app.routes.assets import router as assets_router
from app.routes.brokerage import router as brokerage_router
from app.routes.conversations import router as conversations_router
from app.routes.funding import router as funding_router
from app.routes.market_data import router as market_data_router
from app.routes.onboarding import router as onboarding_router
from app.routes.phone_auth import router as phone_auth_router
from app.routes.plaid_webhooks import router as plaid_webhooks_router
from app.routes.portfolio import router as portfolio_router
from app.routes.radar import router as radar_router
from app.routes.settings import router as settings_router
from app.routes.shortcuts import router as shortcuts_router
from app.routes.trading import router as trading_router

configure_logging(settings.environment)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
        before_send=sentry_before_send,
    )
    sentry_sdk.set_tag("process", "api")

app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.show_docs else None,
    redoc_url="/redoc" if settings.show_docs else None,
    lifespan=lifespan,
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes["APIKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    schema["security"] = [{"APIKeyHeader": []}, {"HTTPBearer": []}]
    # Ensure every operation includes APIKeyHeader so Swagger sends it even
    # when FastAPI auto-generates operation-level security (e.g. HTTPBearer).
    api_key_entry = {"APIKeyHeader": []}
    for path_ops in schema.get("paths", {}).values():
        for operation in path_ops.values():
            if isinstance(operation, dict) and "security" in operation:
                if api_key_entry not in operation["security"]:
                    operation["security"].insert(0, api_key_entry)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

app.state.limiter = limiter


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    response = error_response(429, "Rate limit exceeded", "RATE_LIMIT_EXCEEDED")
    response.headers["Retry-After"] = "60"
    return response


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Middleware executes in reverse registration order (last added = outermost).
# Request flow: CORS → CorrelationID → RequestLogging → APIKey → SlowAPI → route
app.add_middleware(APIKeyMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


def include_routers(app: FastAPI) -> None:
    app.include_router(onboarding_router, prefix="/v1/onboarding", tags=["onboarding"])
    app.include_router(funding_router, prefix="/v1/funding", tags=["funding"])
    app.include_router(assets_router, prefix="/v1/assets", tags=["assets"])
    app.include_router(phone_auth_router, prefix="/v1/auth", tags=["auth"])
    app.include_router(brokerage_router, prefix="/v1/brokerage", tags=["brokerage"])
    app.include_router(portfolio_router, prefix="/v1/portfolio", tags=["portfolio"])
    app.include_router(settings_router, prefix="/v1/settings", tags=["settings"])
    app.include_router(shortcuts_router, prefix="/v1/shortcuts", tags=["shortcuts"])
    app.include_router(trading_router, prefix="/v1/trading", tags=["trading"])
    app.include_router(
        market_data_router, prefix="/v1/market-data", tags=["market-data"]
    )
    app.include_router(radar_router, prefix="/v1/radar", tags=["radar"])
    app.include_router(
        conversations_router, prefix="/v1/conversations", tags=["conversations"]
    )
    app.include_router(
        plaid_webhooks_router, prefix="/v1/plaid/webhooks", tags=["plaid"]
    )
    # Dev-only: lets a developer kick a radar batch on demand. Not mounted
    # in staging/prod so QA can't accidentally trigger production batches.
    if settings.environment == "dev":
        app.include_router(
            admin_radar_router, prefix="/admin/radar", tags=["admin"]
        )


include_routers(app)

@app.get("/")
@limiter.exempt
async def root():
    return {"message": "Sevino API"}


@app.get("/health")
@limiter.exempt
async def health(request: Request, db: AsyncSession = Depends(get_db)):
    db_ok = True
    redis_ok = True

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    try:
        await request.app.state.arq.ping()
    except Exception:
        redis_ok = False

    status = "ok" if (db_ok and redis_ok) else "degraded"
    return JSONResponse(
        status_code=200 if status == "ok" else 503,
        content={
            "status": status,
            "db": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    )

@app.get("/health/auth")
async def auth_health(
    request: Request, 
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("SELECT email FROM auth.users WHERE id = :uid"),
        {"uid": user_id},
    )
    row = result.one_or_none()
    return {"user_id": user_id, "email": row.email if row else None}

