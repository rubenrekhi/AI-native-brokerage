from datetime import date, datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AssetType(StrEnum):
    """The vocabulary stored in `assets.asset_type`.

    Derived from FMP's `isEtf`/`isFund` flags during enrichment; the radar
    candidate sourcer filters on these values. Stored as plain text — this
    enum is the shared contract between producer and consumers.
    """

    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    symbol: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tradeable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    fractionable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alpaca_asset_id: Mapped[Optional[str]] = mapped_column(
        Text, unique=True, nullable=True
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    ipo_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    asset_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
