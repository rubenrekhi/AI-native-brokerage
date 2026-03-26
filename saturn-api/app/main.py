from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.lifecycle import lifespan

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
