"""Debounced ``user_profiles.last_active_at`` maintenance."""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from redis.exceptions import RedisError
from sqlalchemy import update
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.database import async_session
from app.models.user_profile import UserProfile

logger = structlog.get_logger(__name__)

LAST_ACTIVE_DEBOUNCE = timedelta(minutes=15)
LAST_ACTIVE_DEBOUNCE_SECONDS = int(LAST_ACTIVE_DEBOUNCE.total_seconds())
_IN_PROCESS_TOUCH_CACHE: dict[uuid.UUID, datetime] = {}


class UserActivityMiddleware(BaseHTTPMiddleware):
    """Touch authenticated users at most once per debounce window."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        user_id = getattr(request.state, "user_id", None)
        if user_id is not None:
            await self._touch_user(request, user_id)
        return response

    async def _touch_user(self, request: Request, user_id: str) -> None:
        try:
            parsed_user_id = uuid.UUID(user_id)
        except ValueError:
            logger.warning("last_active_touch_invalid_user_id", user_id=user_id)
            return

        now = datetime.now(timezone.utc)
        if not await self._claim_touch_slot(request, parsed_user_id, now):
            return

        cutoff = now - LAST_ACTIVE_DEBOUNCE
        async with async_session() as db:
            try:
                await db.execute(
                    update(UserProfile)
                    .where(
                        UserProfile.id == parsed_user_id,
                        (
                            (UserProfile.last_active_at.is_(None))
                            | (UserProfile.last_active_at < cutoff)
                        ),
                    )
                    .values(last_active_at=now, updated_at=now)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "last_active_touch_failed", user_id=str(parsed_user_id)
                )

    async def _claim_touch_slot(
        self, request: Request, user_id: uuid.UUID, now: datetime
    ) -> bool:
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            try:
                return bool(
                    await redis.set(
                        f"user_activity:last_active:{user_id}",
                        "1",
                        ex=LAST_ACTIVE_DEBOUNCE_SECONDS,
                        nx=True,
                    )
                )
            except RedisError as exc:
                logger.warning(
                    "last_active_debounce_cache_failed",
                    user_id=str(user_id),
                    exc_type=type(exc).__name__,
                )

        cutoff = now - LAST_ACTIVE_DEBOUNCE
        last_touched = _IN_PROCESS_TOUCH_CACHE.get(user_id)
        if last_touched is not None and last_touched >= cutoff:
            return False
        _IN_PROCESS_TOUCH_CACHE[user_id] = now
        return True
