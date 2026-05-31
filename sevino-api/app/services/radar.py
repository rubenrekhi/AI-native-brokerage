"""Business logic for the `/v1/radar` endpoints."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    ConflictError,
    MarketDataUnavailableError,
    NotFoundError,
)
from app.repositories.asset import AssetRepository
from app.repositories.radar_item import (
    AI_ITEM_TTL,
    SOURCE_AI_GENERATED,
    SOURCE_USER_ADDED,
    RadarItemRepository,
)
from app.repositories.user_profile import UserProfileRepository
from app.schemas.radar import RadarItemRead, RadarListResponse
from app.services.market_data import MarketDataService

logger = structlog.get_logger(__name__)


class RadarService:
    def __init__(
        self, market_data: MarketDataService, db: AsyncSession
    ) -> None:
        self._market_data = market_data
        self._db = db

    async def list_for_user(
        self, user_id: uuid.UUID
    ) -> RadarListResponse:
        """Return the user's visible radar rows with live prices merged.

        The response wraps the rows with ``next_refresh_at`` (the user's
        cadence anchor) so iOS can render the right empty-state copy even
        when the list is empty.

        Prices come from `MarketDataService.get_batch_quotes` (FMP-backed,
        cached per-symbol). If the upstream is unavailable, returns the
        rows with null overlay fields — the radar table is the source of
        truth and a missing price overlay is degraded UX, not a 5xx.
        """
        items = await RadarItemRepository.list_for_user(self._db, user_id)
        profile = await UserProfileRepository.get_by_id(self._db, user_id)
        next_refresh_at = profile.next_radar_refresh_at if profile else None

        if not items:
            return RadarListResponse(items=[], next_refresh_at=next_refresh_at)

        symbols = [item.symbol for item in items]
        quotes_by_symbol: dict[str, dict] = {}
        try:
            response = await self._market_data.get_batch_quotes(symbols)
            quotes_by_symbol = {
                q["symbol"]: q for q in response.get("quotes", [])
            }
        except MarketDataUnavailableError:
            logger.warning(
                "radar_quotes_unavailable",
                user_id=str(user_id),
                symbol_count=len(symbols),
            )

        return RadarListResponse(
            items=[
                _build_read(item, quotes_by_symbol.get(item.symbol))
                for item in items
            ],
            next_refresh_at=next_refresh_at,
        )

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
    ) -> RadarItemRead | None:
        """Set the favorite flag on a radar item the user owns.

        Behavior diverges by `source`:

        - ``user_added`` rows unfavorited are deleted (the star is the
          watchlist-membership signal — unstar = remove). Returns
          ``None`` so the route can render 204 No Content.
        - ``ai_generated`` rows have ``expires_at`` adjusted alongside
          the flip: favoriting nulls it (sticky), unfavoriting resets
          it to ``now() + AI_ITEM_TTL``.

        No-op when the row is already at the requested state.

        Post-condition: an unfavorited ``user_added`` row cannot exist
        — the sweep cron and read-time expiry filter can trust this.
        """
        item = await RadarItemRepository.get_by_id_for_user(
            self._db, item_id, user_id
        )
        if item is None:
            raise NotFoundError("Radar item not found")

        if item.is_favorited == is_favorited:
            return RadarItemRead.model_validate(item)

        if not is_favorited and item.source == SOURCE_USER_ADDED:
            await RadarItemRepository.delete(self._db, item)
            logger.info(
                "radar_item_unfavorited_deleted",
                user_id=str(user_id),
                radar_item_id=str(item_id),
                symbol=item.symbol,
            )
            return None

        item.is_favorited = is_favorited
        if item.source == SOURCE_AI_GENERATED:
            item.expires_at = (
                None
                if is_favorited
                else datetime.now(timezone.utc) + AI_ITEM_TTL
            )
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


def _build_read(item, quote: dict | None) -> RadarItemRead:
    """Construct a RadarItemRead from an ORM row + optional quote overlay.

    FMP returns `change_percent` as a percentage value (e.g. "1.24" for
    1.24%); the radar schema's `change_pct` is `PctStr` (factor of 1, so
    0.0124 for 1.24%). The conversion happens here at the boundary.
    """
    base = RadarItemRead.model_validate(item)
    if quote is None:
        return base
    return base.model_copy(
        update={
            "price": Decimal(quote["price"]),
            "change_abs": Decimal(quote["change"]),
            "change_pct": Decimal(quote["change_percent"]) / Decimal(100),
        }
    )
