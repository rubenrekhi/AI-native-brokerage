from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.exceptions import register_exception_handlers
from app.lifecycle import lifespan
from app.logging_config import configure_logging
from app.middleware import CorrelationIDMiddleware, RequestLoggingMiddleware

configure_logging(settings.environment)

app = FastAPI(
    title=settings.APP_NAME,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.show_docs else None,
    redoc_url="/redoc" if settings.show_docs else None,
    lifespan=lifespan,
)

# Middleware executes in reverse registration order (last added = outermost).
# CorrelationIDMiddleware must wrap RequestLoggingMiddleware so the ID is
# available when the request reaches the logging layer.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

@app.get("/")
async def root():
    return {"message": "Saturn API (by Sevino)"}


@app.get("/health")
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
