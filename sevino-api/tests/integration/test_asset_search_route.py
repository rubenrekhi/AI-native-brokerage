"""Integration tests for GET /v1/assets/search against real local Postgres.

Seeds assets directly into the test DB and exercises the full route
stack (schema validation → repository → SQL) via `authenticated_db_client`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


async def _seed(db_session: AsyncSession, rows: list[dict]) -> None:
    for row in rows:
        await db_session.execute(
            text(
                """
                INSERT INTO assets (symbol, name, exchange, tradeable, logo_url)
                VALUES (:symbol, :name, :exchange, :tradeable, :logo_url)
                """
            ),
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "exchange": row.get("exchange"),
                "tradeable": row.get("tradeable", True),
                "logo_url": row.get("logo_url"),
            },
        )
    await db_session.flush()


@pytest.fixture
async def seed_five(db_session: AsyncSession):
    """Five assets — mix of tradeable/untradeable, ticker/name overlap on 'TS'."""
    await _seed(
        db_session,
        [
            {
                "symbol": "TSLA",
                "name": "Tesla, Inc.",
                "logo_url": "https://financialmodelingprep.com/image-stock/TSLA.png",
            },
            {
                "symbol": "TSM",
                "name": "Taiwan Semiconductor Manufacturing Company Limited",
                "logo_url": "https://financialmodelingprep.com/image-stock/TSM.png",
            },
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "logo_url": "https://financialmodelingprep.com/image-stock/AAPL.png",
            },
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corporation",
                "logo_url": "https://financialmodelingprep.com/image-stock/NVDA.png",
            },
            {
                "symbol": "TSDEAD",
                "name": "Delisted TS Corp",
                "tradeable": False,
                "logo_url": "https://financialmodelingprep.com/image-stock/TSDEAD.png",
            },
        ],
    )


class TestSearchEndpoint:
    async def test_ticker_prefix_returns_matches(
        self, authenticated_db_client, seed_five
    ):
        response = await authenticated_db_client.get(
            "/v1/assets/search?q=TS&limit=10"
        )

        assert response.status_code == 200
        body = response.json()
        symbols = [r["symbol"] for r in body]
        assert "TSLA" in symbols
        assert "TSM" in symbols

    async def test_name_substring_returns_match(
        self, authenticated_db_client, seed_five
    ):
        response = await authenticated_db_client.get(
            "/v1/assets/search?q=tesla&limit=10"
        )

        assert response.status_code == 200
        symbols = [r["symbol"] for r in response.json()]
        assert symbols == ["TSLA"]

    async def test_no_matches_returns_empty_array(
        self, authenticated_db_client, seed_five
    ):
        response = await authenticated_db_client.get(
            "/v1/assets/search?q=ZZZZ&limit=10"
        )

        assert response.status_code == 200
        assert response.json() == []

    async def test_untradeable_assets_excluded(
        self, authenticated_db_client, seed_five
    ):
        response = await authenticated_db_client.get(
            "/v1/assets/search?q=TS&limit=10"
        )

        assert response.status_code == 200
        symbols = [r["symbol"] for r in response.json()]
        assert "TSDEAD" not in symbols

    async def test_response_shape_includes_symbol_name_logo(
        self, authenticated_db_client, seed_five
    ):
        response = await authenticated_db_client.get(
            "/v1/assets/search?q=TSLA&limit=1"
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0] == {
            "symbol": "TSLA",
            "name": "Tesla, Inc.",
            "logo_url": "https://financialmodelingprep.com/image-stock/TSLA.png",
        }
