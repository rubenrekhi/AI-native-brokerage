from app.services.digest.generators.dividends import DividendsGenerator
from app.services.digest.generators.pending_orders import PendingOrdersGenerator
from app.services.digest.generators.radar_refresh import RadarRefreshGenerator
from app.services.digest.types import Generator

KNOWN_GENERATORS = (
    DividendsGenerator,
    PendingOrdersGenerator,
    RadarRefreshGenerator,
)


def create_known_generators() -> list[Generator]:
    return [generator_cls() for generator_cls in KNOWN_GENERATORS]

__all__ = [
    "DividendsGenerator",
    "PendingOrdersGenerator",
    "RadarRefreshGenerator",
    "KNOWN_GENERATORS",
    "create_known_generators",
]
