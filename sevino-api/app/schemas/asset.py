"""Pydantic models for /v1/assets/* endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class AssetSearchQuery(BaseModel):
    q: str = Field(..., min_length=1, max_length=10)
    limit: int = Field(default=10, ge=1, le=50)


class AssetSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    name: str
    logo_url: str | None = None
