"""Built-in Daily Digest generators."""

from __future__ import annotations

from app.services.digest.generators.big_moves import BigMovesGenerator
from app.services.digest.generators.dividends import DividendsGenerator
from app.services.digest.generators.market_context import MarketContextGenerator
from app.services.digest.generators.pending_orders import PendingOrdersGenerator
from app.services.digest.generators.radar_refresh import RadarRefreshGenerator
from app.services.digest.generators.watchlist import WatchlistMovesGenerator
from app.services.digest.moves import StockBarsProvider
from app.services.digest.types import Generator

ACTIVITY_GENERATORS = (
    DividendsGenerator,
    PendingOrdersGenerator,
    RadarRefreshGenerator,
)
PRICE_MOVE_GENERATORS = (
    BigMovesGenerator,
    WatchlistMovesGenerator,
    MarketContextGenerator,
)
KNOWN_GENERATORS = ACTIVITY_GENERATORS + PRICE_MOVE_GENERATORS


def create_known_generators(
    market_data: StockBarsProvider | None = None,
) -> list[Generator]:
    generators: list[Generator] = [
        generator_cls() for generator_cls in ACTIVITY_GENERATORS
    ]
    if market_data is not None:
        generators.extend(
            generator_cls(market_data) for generator_cls in PRICE_MOVE_GENERATORS
        )
    return generators


def build_known_generators(market_data: StockBarsProvider) -> list[Generator]:
    return create_known_generators(market_data)


__all__ = (
    "BigMovesGenerator",
    "DividendsGenerator",
    "MarketContextGenerator",
    "PendingOrdersGenerator",
    "RadarRefreshGenerator",
    "WatchlistMovesGenerator",
    "ACTIVITY_GENERATORS",
    "PRICE_MOVE_GENERATORS",
    "KNOWN_GENERATORS",
    "create_known_generators",
    "build_known_generators",
)
