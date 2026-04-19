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
from app.database import get_db
from app.exceptions import error_response, register_exception_handlers
from app.lifecycle import lifespan
from app.logging_config import configure_logging
from app.middleware import APIKeyMiddleware, CorrelationIDMiddleware, RequestLoggingMiddleware
from app.rate_limit import limiter
from app.routes.onboarding import router as onboarding_router

configure_logging(settings.environment)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
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

