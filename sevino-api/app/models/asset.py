from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


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
