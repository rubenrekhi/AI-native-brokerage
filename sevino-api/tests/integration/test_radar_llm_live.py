"""Live RadarLLM call against the real model.

Env-gated: set ``RUN_LIVE_LLM_TESTS=1`` (and a valid ANTHROPIC_API_KEY) to
run. Builds a 40-candidate pool spanning all four buckets plus a realistic
user context, then asserts every returned pick passes the same validation
the pipeline enforces.
"""

import os

import pytest

from app.ai.anthropic_client import create_anthropic_client
from app.services.radar_job.candidate_sourcer import (
    BUCKET_BROAD_NOTABLE,
    BUCKET_DIVERSIFICATION,
    BUCKET_OWNED_SECTOR,
    BUCKET_UPCOMING_EVENT,
    Candidate,
)
from app.services.radar_job.llm import (
    MAX_PICKS,
    MIN_PICKS,
    OwnedPosition,
    RadarLLM,
    UserContext,
    validate_pick,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="live LLM test — set RUN_LIVE_LLM_TESTS=1 to run",
)

_SECTORS = [
    "Technology", "Financials", "Healthcare", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
    "Real Estate", "Communication Services",
]


def _fixture_pool() -> list[Candidate]:
    pool: list[Candidate] = []

    owned = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"), ("CRM", "Salesforce")]
    for sym, name in owned:
        pool.append(Candidate(sym, name, "Technology", 1_000_000_000_000, BUCKET_OWNED_SECTOR))

    diversification = [
        ("JPM", "JPMorgan", "Financials"), ("UNH", "UnitedHealth", "Healthcare"),
        ("XOM", "Exxon", "Energy"), ("CAT", "Caterpillar", "Industrials"),
        ("HD", "Home Depot", "Consumer Discretionary"), ("DUK", "Duke Energy", "Utilities"),
        ("LIN", "Linde", "Materials"), ("AMT", "American Tower", "Real Estate"),
        ("DIS", "Disney", "Communication Services"), ("PG", "Procter & Gamble", "Consumer Staples"),
    ]
    for sym, name, sector in diversification:
        pool.append(Candidate(sym, name, sector, 200_000_000_000, BUCKET_DIVERSIFICATION))

    from datetime import date, timedelta

    soon = date.today() + timedelta(days=4)
    events = [
        ("KO", "Coca-Cola", "Consumer Staples"), ("PEP", "PepsiCo", "Consumer Staples"),
        ("MCD", "McDonald's", "Consumer Discretionary"), ("V", "Visa", "Financials"),
        ("MA", "Mastercard", "Financials"), ("ABBV", "AbbVie", "Healthcare"),
        ("CVX", "Chevron", "Energy"), ("WMT", "Walmart", "Consumer Staples"),
    ]
    for sym, name, sector in events:
        pool.append(
            Candidate(sym, name, sector, 300_000_000_000, BUCKET_UPCOMING_EVENT, next_earnings_date=soon)
        )

    notable = [
        ("GOOGL", "Alphabet", "Communication Services"), ("AMZN", "Amazon", "Consumer Discretionary"),
        ("META", "Meta", "Communication Services"), ("BRK.B", "Berkshire", "Financials"),
        ("LLY", "Eli Lilly", "Healthcare"), ("AVGO", "Broadcom", "Technology"),
        ("TSLA", "Tesla", "Consumer Discretionary"), ("COST", "Costco", "Consumer Staples"),
        ("ORCL", "Oracle", "Technology"), ("NFLX", "Netflix", "Communication Services"),
        ("ADBE", "Adobe", "Technology"), ("BAC", "Bank of America", "Financials"),
        ("KO2", "Synthetic Co", "Industrials"), ("WM", "Waste Management", "Industrials"),
        ("SO", "Southern Co", "Utilities"), ("SHW", "Sherwin-Williams", "Materials"),
        ("PLD", "Prologis", "Real Estate"), ("TMO", "Thermo Fisher", "Healthcare"),
    ]
    for sym, name, sector in notable:
        pool.append(Candidate(sym, name, sector, 250_000_000_000, BUCKET_BROAD_NOTABLE))

    return pool


async def test_live_pick_returns_valid_descriptive_picks():
    pool = _fixture_pool()
    assert len(pool) >= 40
    known_sectors = set(_SECTORS)
    assert all(c.sector in known_sectors for c in pool)

    ctx = UserContext(
        risk_tolerance="moderate",
        age=34,
        goals=["long-term growth", "retirement"],
        positions=[
            OwnedPosition("AAPL", "Technology"),
            OwnedPosition("MSFT", "Technology"),
            OwnedPosition("NVDA", "Technology"),
        ],
        favorited_symbols=["TSLA"],
    )

    llm = RadarLLM(create_anthropic_client())
    picks = await llm.pick(pool, ctx)

    pool_by_symbol = {c.symbol.upper(): c for c in pool}
    assert MIN_PICKS <= len(picks) <= MAX_PICKS
    for pick in picks:
        assert validate_pick(pick, pool_by_symbol) == [], pick
        assert len(pick.label) <= 120
    # Should span more than one bucket per the prompt's diversification rule.
    assert len({p.bucket for p in picks}) >= 2
