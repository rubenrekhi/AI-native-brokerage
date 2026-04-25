"""FastAPI router for /v1/assets/*. Searches the local asset cache (not Alpaca directly)."""

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
    return await AssetRepository.search(db, query.q, query.limit)
