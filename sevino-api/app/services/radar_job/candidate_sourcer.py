"""Per-user candidate pool builder for the AI Radar (product spec §13.1).

Stage 3 of the radar pipeline. Given the universe-wide gated asset list
(from `StaticQualityGate`), this assembles a richer-than-final pool of
~30–50 bucket-tagged candidates that the downstream LLM picks 5–7 from. The
sourcer does *not* pick — it gathers meaningful choice across four buckets
and attaches the metadata the LLM needs to write a good descriptive label.

Positions are not stored locally: they're fetched live from Alpaca. A
just-onboarded user's account is still `SUBMITTED` (not `ACTIVE`), so their
first batch has empty positions and the `owned_sector` bucket stays empty —
diversification / event / notable carry it. Alpaca being unreachable
degrades to empty positions rather than failing the batch.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.repositories.asset import AssetRepository
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    BrokerageAccountRepository,
)
from app.repositories.radar_item import RadarItemRepository
from app.services.alpaca_broker import (
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)
from app.services.radar_job.events_client import EventsClient

logger = structlog.get_logger(__name__)


BUCKET_OWNED_SECTOR = "owned_sector"
BUCKET_DIVERSIFICATION = "diversification"
BUCKET_UPCOMING_EVENT = "upcoming_event"
BUCKET_BROAD_NOTABLE = "broad_notable"

OWNED_SECTOR_PER_SECTOR = 4
OWNED_SECTOR_CAP = 20
DIVERSIFICATION_PER_SECTOR = 2
DIVERSIFICATION_CAP = 10
UPCOMING_EVENT_CAP = 10
BROAD_NOTABLE_CAP = 10


@dataclass
class Candidate:
    symbol: str
    name: str
    sector: str | None
    market_cap: int | None
    bucket: str
    # Enriched downstream by the LLM step; the sourcer leaves them unset.
    last_price: Decimal | None = None
    one_month_return_pct: Decimal | None = None
    next_earnings_date: date | None = None
    next_dividend_date: date | None = None


async def build_pool(
    user_id: UUID,
    gated_universe: list[Asset],
    db: AsyncSession,
    alpaca: AlpacaBrokerService,
    events: EventsClient,
) -> list[Candidate]:
    """Assemble a bucket-tagged candidate pool for one user.

    Buckets fire in priority order and a symbol is claimed by the first
    bucket that selects it — the broad megacaps that fill `broad_notable`
    would otherwise duplicate names already surfaced by `owned_sector` /
    `diversification`, so the running exclude set dedupes across buckets.
    """
    owned_symbols, owned_sectors = await _load_positions(user_id, db, alpaca)
    existing_radar = await RadarItemRepository.list_all_symbols(db, user_id)

    exclude = {s.upper() for s in owned_symbols | existing_radar}

    pool: list[Candidate] = []
    _accumulate(pool, exclude, _owned_sector_bucket(gated_universe, owned_sectors, exclude))
    _accumulate(pool, exclude, _diversification_bucket(gated_universe, owned_sectors, exclude))
    _accumulate(pool, exclude, await _upcoming_event_bucket(gated_universe, exclude, events))
    _accumulate(pool, exclude, _broad_notable_bucket(gated_universe, exclude))

    logger.info(
        "radar_candidate_pool_built",
        user_id=str(user_id),
        total=len(pool),
        owned_sectors=len(owned_sectors),
    )
    return pool


async def _load_positions(
    user_id: UUID, db: AsyncSession, alpaca: AlpacaBrokerService
) -> tuple[set[str], set[str]]:
    brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)
    if not brokerage or brokerage.account_status != STATUS_ACTIVE:
        return set(), set()

    try:
        raw = await alpaca.list_positions(brokerage.alpaca_account_id)
    except AlpacaBrokerUnavailableError:
        logger.warning("radar_positions_unavailable", user_id=str(user_id))
        return set(), set()

    owned_symbols = {p["symbol"].upper() for p in raw if p.get("symbol")}
    owned_sectors = await AssetRepository.sectors_for_symbols(db, owned_symbols)
    return owned_symbols, owned_sectors


def _accumulate(
    pool: list[Candidate], exclude: set[str], candidates: list[Candidate]
) -> None:
    for candidate in candidates:
        key = candidate.symbol.upper()
        if key in exclude:
            continue
        exclude.add(key)
        pool.append(candidate)


def _owned_sector_bucket(
    gated: list[Asset], owned_sectors: set[str], exclude: set[str]
) -> list[Candidate]:
    out: list[Candidate] = []
    for sector in sorted(owned_sectors):
        if len(out) >= OWNED_SECTOR_CAP:
            break
        in_sector = [
            a
            for a in gated
            if a.sector == sector and a.symbol.upper() not in exclude
        ]
        for asset in _top_by_market_cap(in_sector, OWNED_SECTOR_PER_SECTOR):
            out.append(_candidate(asset, BUCKET_OWNED_SECTOR))
    return out[:OWNED_SECTOR_CAP]


def _diversification_bucket(
    gated: list[Asset], owned_sectors: set[str], exclude: set[str]
) -> list[Candidate]:
    missing = {a.sector for a in gated if a.sector} - owned_sectors
    out: list[Candidate] = []
    for sector in sorted(missing):
        if len(out) >= DIVERSIFICATION_CAP:
            break
        in_sector = [
            a
            for a in gated
            if a.sector == sector and a.symbol.upper() not in exclude
        ]
        for asset in _top_by_market_cap(in_sector, DIVERSIFICATION_PER_SECTOR):
            out.append(_candidate(asset, BUCKET_DIVERSIFICATION))
    return out[:DIVERSIFICATION_CAP]


async def _upcoming_event_bucket(
    gated: list[Asset], exclude: set[str], events: EventsClient
) -> list[Candidate]:
    earnings = _earliest_date_by_symbol(await events.upcoming_earnings())
    dividends = _earliest_date_by_symbol(await events.upcoming_dividends())
    event_symbols = set(earnings) | set(dividends)

    matched = [
        a
        for a in gated
        if a.symbol.upper() in event_symbols and a.symbol.upper() not in exclude
    ]
    out: list[Candidate] = []
    for asset in _top_by_market_cap(matched, UPCOMING_EVENT_CAP):
        out.append(
            _candidate(
                asset,
                BUCKET_UPCOMING_EVENT,
                next_earnings_date=earnings.get(asset.symbol.upper()),
                next_dividend_date=dividends.get(asset.symbol.upper()),
            )
        )
    return out


def _broad_notable_bucket(
    gated: list[Asset], exclude: set[str]
) -> list[Candidate]:
    eligible = [a for a in gated if a.symbol.upper() not in exclude]
    return [
        _candidate(a, BUCKET_BROAD_NOTABLE)
        for a in _top_by_market_cap(eligible, BROAD_NOTABLE_CAP)
    ]


def _top_by_market_cap(assets: list[Asset], n: int) -> list[Asset]:
    return sorted(assets, key=lambda a: a.market_cap or 0, reverse=True)[:n]


def _candidate(asset: Asset, bucket: str, **metadata) -> Candidate:
    return Candidate(
        symbol=asset.symbol,
        name=asset.name,
        sector=asset.sector,
        market_cap=asset.market_cap,
        bucket=bucket,
        **metadata,
    )


def _earliest_date_by_symbol(rows: list[dict]) -> dict[str, date]:
    """Map each symbol to its earliest (next) event date in the window.

    Skips rows with a missing or unparseable date; a symbol with several
    events keeps only the soonest.
    """
    out: dict[str, date] = {}
    for row in rows:
        symbol = row.get("symbol")
        parsed = _parse_date(row.get("date"))
        if not symbol or parsed is None:
            continue
        key = symbol.upper()
        if key not in out or parsed < out[key]:
            out[key] = parsed
    return out


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
