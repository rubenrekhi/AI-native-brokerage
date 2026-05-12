"""Business logic for the `/v1/radar` endpoints."""

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError
from app.repositories.asset import AssetRepository
from app.repositories.radar_item import RadarItemRepository
from app.schemas.radar import RadarItemRead

logger = structlog.get_logger(__name__)


class RadarService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_user(
        self, user_id: uuid.UUID
    ) -> list[RadarItemRead]:
        """Return the user's visible radar rows."""
        items = await RadarItemRepository.list_for_user(self._db, user_id)
        return [RadarItemRead.model_validate(item) for item in items]

    async def add_user_item(
        self, user_id: uuid.UUID, symbol: str
    ) -> RadarItemRead:
        """Add a user-chosen ticker to their radar.

        Symbol is normalized to uppercase and validated against the
        `assets` catalog (rejects non-tradeable / unknown tickers). The
        DB-level unique constraint on `(user_id, symbol)` is the source
        of truth for duplicates — we let the insert fail and translate
        the `IntegrityError` so race-condition POSTs surface as 409
        instead of 500.
        """
        normalized = symbol.upper()

        asset = await AssetRepository.get_by_symbol(self._db, normalized)
        if asset is None:
            logger.warning(
                "radar_blocked_symbol_not_tradeable",
                user_id=str(user_id),
                symbol=normalized,
            )
            raise ConflictError(
                f"{normalized} is not available for trading.",
                code="SYMBOL_NOT_TRADEABLE",
                detail={"symbol": normalized},
            )

        try:
            item = await RadarItemRepository.create_user_added(
                self._db,
                user_id=user_id,
                symbol=normalized,
                company_name=asset.name,
            )
        except IntegrityError as exc:
            raise ConflictError(
                f"{normalized} is already on your radar.",
                code="RADAR_DUPLICATE_SYMBOL",
                detail={"symbol": normalized},
            ) from exc

        logger.info(
            "radar_user_item_added",
            user_id=str(user_id),
            symbol=normalized,
            radar_item_id=str(item.id),
        )
        return RadarItemRead.model_validate(item)
