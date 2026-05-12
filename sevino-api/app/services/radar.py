"""Business logic for the `/v1/radar` endpoints."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.radar_item import RadarItemRepository
from app.schemas.radar import RadarItemRead


class RadarService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_user(
        self, user_id: uuid.UUID
    ) -> list[RadarItemRead]:
        """Return the user's visible radar rows."""
        items = await RadarItemRepository.list_for_user(self._db, user_id)
        return [RadarItemRead.model_validate(item) for item in items]
