"""Seed and verify a deterministic Daily Digest fixture user.

Run:
    uv run python scripts/seed_digest.py

The script writes only local DB rows for the user, brokerage account, and
favorited radar items. Portfolio, dividend, order, market-data, and earnings
inputs are fixture providers, so no external Alpaca/FMP/Anthropic calls are
needed. It persists one generated digest snapshot and fails if the expected
card kinds are missing.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import async_session
from app.schemas.fmp import EarningsCalendarItem, HistoricalEarningsItem
from app.services.digest.context import ET
from app.services.digest.generators import build_known_generators
from app.services.digest.reranker import RerankResult
from app.services.digest.service import DigestService
from app.services.fmp import StockNewsItem

TEST_EMAIL = "digest-e2e@sevino.test"
TEST_USER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, TEST_EMAIL)
ALPACA_ACCOUNT_ID = "digest-fixture-account"
EXPECTED_KINDS = {"dividends", "big_move", "earnings_result", "market_context"}


class FixtureAlpaca:
    async def get_trading_account(self, _account_id: str) -> dict[str, str]:
        return {"equity": "100000"}

    async def list_positions(self, _account_id: str) -> list[dict[str, str]]:
        return [
            {"symbol": "AAPL", "name": "Apple", "market_value": "35000"},
            {"symbol": "JPM", "name": "JPMorgan Chase", "market_value": "20000"},
            {"symbol": "XOM", "name": "Exxon Mobil", "market_value": "15000"},
            {"symbol": "UNH", "name": "UnitedHealth", "market_value": "15000"},
            {"symbol": "NVDA", "name": "NVIDIA", "market_value": "15000"},
        ]

    async def get_dividend_activities(self, *, account_id: str) -> list[dict[str, str]]:
        paid_at = datetime.now(timezone.utc) - timedelta(hours=2)
        return [
            {
                "id": "digest-div-1",
                "symbol": "JPM",
                "net_amount": "8.42",
                "status": "executed",
                "created_at": paid_at.isoformat(),
            }
        ]

    async def list_orders(self, *_args: Any, **_kwargs: Any) -> list[dict[str, str]]:
        filled_at = datetime.now(timezone.utc) - timedelta(hours=3)
        return [
            {
                "id": "digest-order-1",
                "client_order_id": "manual-digest-1",
                "symbol": "NVDA",
                "side": "buy",
                "qty": "1",
                "notional": "750.00",
                "filled_qty": "1",
                "status": "filled",
                "filled_at": filled_at.isoformat(),
            }
        ]


class FixtureMarketData:
    _prev_close = {
        "AAPL": Decimal("100"),
        "AMD": Decimal("100"),
        "SNOW": Decimal("100"),
        "SPY": Decimal("500"),
        "QQQ": Decimal("450"),
    }
    _current = {
        "AAPL": Decimal("105"),
        "AMD": Decimal("104"),
        "SNOW": Decimal("96"),
        "SPY": Decimal("505"),
        "QQQ": Decimal("455.40"),
    }

    async def get_stock_bars(
        self,
        symbol: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int = 10000,
    ) -> list[dict[str, str]]:
        normalized = symbol.upper()
        now = end or datetime.now(timezone.utc)
        session_date = _prior_close(now.astimezone(ET)).date().isoformat()
        if timeframe == "1Day":
            return [
                {
                    "t": session_date,
                    "c": str(self._prev_close.get(normalized, Decimal("100"))),
                }
            ]
        return [
            {
                "t": now.isoformat(),
                "c": str(self._current.get(normalized, Decimal("100"))),
            }
        ]


class FixtureFmp:
    def __init__(self) -> None:
        self._report_date = _prior_close(datetime.now(ET)).date()

    async def get_historical_earnings(
        self, symbol: str, limit: int = 1
    ) -> list[HistoricalEarningsItem]:
        if symbol.upper() != "AAPL":
            return []
        return [
            HistoricalEarningsItem(
                symbol="AAPL",
                reported_date=self._report_date,
                time="amc",
                eps_actual=Decimal("2.10"),
                eps_estimate=Decimal("1.90"),
                revenue_actual=Decimal("125000000000"),
                revenue_estimate=Decimal("120000000000"),
            )
        ]

    async def get_earnings_calendar(
        self, *_args: Any, **_kwargs: Any
    ) -> list[EarningsCalendarItem]:
        return []

    async def get_stock_news(
        self, symbols: list[str], since: datetime, limit: int = 50
    ) -> list[StockNewsItem]:
        published_at = datetime.now(timezone.utc) - timedelta(hours=1)
        return [
            StockNewsItem(
                symbol="AAPL",
                title="AAPL shares rise after earnings update",
                site="Fixture Wire",
                url="https://example.com/digest/aapl",
                publishedDate=published_at,
                text="Apple reported stronger results in the fixture dataset.",
            )
        ]


class KeepAllReranker:
    async def rank_with_metadata(self, candidates, *_args, **_kwargs):
        return RerankResult(
            ordered_ids=[candidate.card.id for candidate in candidates],
            used_fallback=False,
        )


async def _seed_db() -> None:
    async with async_session() as db:
        await db.execute(
            text(
                """
                INSERT INTO auth.users (
                    id, instance_id, email, encrypted_password,
                    aud, role, raw_app_meta_data, raw_user_meta_data,
                    created_at, updated_at, confirmation_token, email_change,
                    email_change_token_new, recovery_token
                ) VALUES (
                    :id, '00000000-0000-0000-0000-000000000000', :email, '',
                    'authenticated', 'authenticated', '{}', '{}',
                    now(), now(), '', '', '', ''
                )
                ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, updated_at = now()
                """
            ),
            {"id": TEST_USER_ID, "email": TEST_EMAIL},
        )
        await db.execute(
            text(
                """
                INSERT INTO user_profiles (
                    id, email, onboarding_completed, last_active_at,
                    next_radar_refresh_at, created_at, updated_at
                ) VALUES (
                    :id, :email, true, now(), now(), now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    onboarding_completed = true,
                    last_active_at = now(),
                    next_radar_refresh_at = now(),
                    updated_at = now()
                """
            ),
            {"id": TEST_USER_ID, "email": TEST_EMAIL},
        )
        await db.execute(
            text(
                """
                INSERT INTO brokerage_accounts (
                    id, user_id, alpaca_account_id, account_status,
                    kyc_submitted_at, activated_at, created_at, updated_at
                ) VALUES (
                    :id, :user_id, :alpaca_account_id, 'ACTIVE',
                    now(), now(), now(), now()
                )
                ON CONFLICT (user_id) DO UPDATE SET
                    alpaca_account_id = EXCLUDED.alpaca_account_id,
                    account_status = 'ACTIVE',
                    activated_at = COALESCE(brokerage_accounts.activated_at, now()),
                    updated_at = now()
                """
            ),
            {
                "id": uuid.uuid4(),
                "user_id": TEST_USER_ID,
                "alpaca_account_id": ALPACA_ACCOUNT_ID,
            },
        )
        for symbol, name in (("AMD", "Advanced Micro Devices"), ("SNOW", "Snowflake")):
            await db.execute(
                text(
                    """
                    INSERT INTO radar_items (
                        id, user_id, symbol, company_name, source, is_favorited,
                        expires_at, created_at, updated_at
                    ) VALUES (
                        :id, :user_id, :symbol, :name, 'user_added', true,
                        NULL, now(), now()
                    )
                    ON CONFLICT (user_id, symbol) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        is_favorited = true,
                        expires_at = NULL,
                        updated_at = now()
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "user_id": TEST_USER_ID,
                    "symbol": symbol,
                    "name": name,
                },
            )
        await db.commit()


async def _generate_and_assert() -> set[str]:
    async with async_session() as db:
        market_data = FixtureMarketData()
        fmp = FixtureFmp()
        service = DigestService(
            db,
            alpaca=FixtureAlpaca(),
            market_data=market_data,
            fmp=fmp,
            generators=build_known_generators(market_data, fmp=fmp),
            reranker=KeepAllReranker(),
        )
        snapshot = await service.generate_for_user(TEST_USER_ID)
        await db.commit()
        kinds = {card["kind"] for card in snapshot.cards}
        missing = EXPECTED_KINDS - kinds
        if missing:
            raise RuntimeError(
                f"Digest fixture missing expected card kinds: {sorted(missing)}; "
                f"got {sorted(kinds)}"
            )
        return kinds


def _prior_close(now_et: datetime) -> datetime:
    close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et.weekday() < 5 and now_et >= close:
        return close
    day = now_et.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, time(16), tzinfo=ET)


async def _main() -> int:
    if settings.environment != "dev":
        raise RuntimeError(
            "seed_digest.py writes fixture rows and only runs against a local "
            f"dev database (ENVIRONMENT={settings.environment!r})"
        )
    await _seed_db()
    kinds = await _generate_and_assert()
    print(f"Seeded digest fixture user: {TEST_EMAIL}")
    print(f"user_id: {TEST_USER_ID}")
    print(f"card_kinds: {', '.join(sorted(kinds))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
