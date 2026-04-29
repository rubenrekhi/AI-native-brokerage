from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sse_checkpoint import SseCheckpoint


class SseCheckpointRepository:

    @staticmethod
    async def get(db: AsyncSession, stream_name: str) -> SseCheckpoint | None:
        result = await db.execute(
            select(SseCheckpoint).where(SseCheckpoint.stream_name == stream_name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert(
        db: AsyncSession, stream_name: str, last_event_id: str | None
    ) -> None:
        stmt = insert(SseCheckpoint).values(
            stream_name=stream_name, last_event_id=last_event_id
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["stream_name"],
            set_={
                "last_event_id": stmt.excluded.last_event_id,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
