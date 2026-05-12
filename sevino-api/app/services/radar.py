"""Business logic for the `/v1/radar` endpoints."""

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
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

    async def toggle_favorite(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        is_favorited: bool,
    ) -> RadarItemRead:
        """Set the favorite flag on a radar item the user owns.

        T9 scope: basic flag toggle only. Source-specific behavior
        (delete-on-unfavorite for `user_added` rows, expires_at reset for
        `ai_generated` rows) is layered on in T10 — until then, an
        unfavorited `user_added` row can exist transiently.
        """
        item = await RadarItemRepository.get_by_id_for_user(
            self._db, item_id, user_id
        )
        if item is None:
            raise NotFoundError("Radar item not found")

        if item.is_favorited == is_favorited:
            return RadarItemRead.model_validate(item)

        item.is_favorited = is_favorited
        await self._db.flush()
        await self._db.refresh(item)
        return RadarItemRead.model_validate(item)

    async def remove(self, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Hard-delete a radar item the user owns.

        Cross-user attempts surface as 404 (not 403) so the API doesn't
        leak whether the id exists under another account.
        """
        item = await RadarItemRepository.get_by_id_for_user(
            self._db, item_id, user_id
        )
        if item is None:
            raise NotFoundError("Radar item not found")

        await RadarItemRepository.delete(self._db, item)
        logger.info(
            "radar_item_removed",
            user_id=str(user_id),
            radar_item_id=str(item_id),
            symbol=item.symbol,
        )
