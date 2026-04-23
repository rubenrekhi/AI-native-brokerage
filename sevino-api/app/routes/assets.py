"""FastAPI router for /v1/assets/*.

Backs the iOS ticker-mention UI: the client debounces input and hits
`/search` for typeahead results over the locally cached Alpaca asset
universe. Auth-gated; rate-limited via the global per-user default.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.repositories.asset import AssetRepository
from app.schemas.asset import AssetSearchQuery, AssetSearchResult

router = APIRouter()


@router.get("/search", response_model=list[AssetSearchResult])
async def search_assets(
    query: AssetSearchQuery = Depends(),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AssetSearchResult]:
    """Typeahead search over the tradeable asset cache."""
    return await AssetRepository.search(db, query.q, query.limit)
