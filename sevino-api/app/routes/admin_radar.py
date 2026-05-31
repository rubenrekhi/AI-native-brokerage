"""Dev-only admin endpoints for the AI Radar pipeline.

Mounted under `/admin/radar` only when ``settings.environment == "dev"``
(see ``app.main.include_routers``). Lets a developer kick a fresh batch
generation for their own user without waiting for the hourly cron.
"""

import uuid
from datetime import date

import structlog
from fastapi import APIRouter, Depends, Query, Request

from app.auth import get_current_user
from app.exceptions import AuthorizationError

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/generate")
async def trigger_radar_batch(
    request: Request,
    user_id: uuid.UUID = Query(..., description="User to generate a batch for"),
    authenticated_user_id: str = Depends(get_current_user),
) -> dict:
    """Enqueue ``generate_radar_batch`` for the authenticated user.

    The job_id is deterministic per-user-per-day, so two clicks in the
    same UTC day collapse to one ARQ job.
    """
    if str(user_id) != authenticated_user_id:
        raise AuthorizationError(
            "Admin trigger is limited to the authenticated user"
        )

    job_id = f"radar_batch:{user_id}:{date.today().isoformat()}"
    job = await request.app.state.arq.enqueue_job(
        "generate_radar_batch",
        str(user_id),
        _job_id=job_id,
    )
    enqueued = job is not None
    logger.info(
        "admin_radar_batch_enqueued",
        user_id=str(user_id),
        job_id=job_id,
        enqueued=enqueued,
    )
    return {"job_id": job_id, "enqueued": enqueued}
