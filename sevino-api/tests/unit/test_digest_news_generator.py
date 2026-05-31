from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.services.digest.cards import NewsCard
from app.services.digest.generators import build_known_generators
from app.services.digest.generators.news import NewsGenerator
from app.services.digest.types import DigestContext, MarketState
from app.services.fmp import StockNewsItem

NOW = datetime(2026, 5, 31, 16, 0, tzinfo=timezone.utc)


class FakeStockNews:
    def __init__(
        self,
        items: list[StockNewsItem] | None = None,
        *,
        exc: Exception | None = None,
    ) -> None:
        self.items = items or []
        self.exc = exc
        self.calls: list[SimpleNamespace] = []

    async def get_stock_news(
        self, symbols: list[str], since: datetime, limit: int = 50
    ) -> list[StockNewsItem]:
        self.calls.append(SimpleNamespace(symbols=symbols, since=since, limit=limit))
        if self.exc is not None:
            raise self.exc
        return self.items


def _ctx(*holdings: dict) -> DigestContext:
    return DigestContext(
        user_id=uuid4(),
        portfolio_snapshot=None,
        holdings=list(holdings),
        financial_profile=None,
        market_state=MarketState(as_of=NOW, session="closed"),
    )


def _holding(symbol: str, weight: str = "0.25") -> dict:
    return {"symbol": symbol, "weight": weight}


def _news(
    title: str,
    published_at: datetime,
    *,
    symbol: str = "AAPL",
    text: str | None = "Digestible summary",
    body: str | None = None,
) -> StockNewsItem:
    return StockNewsItem.model_validate(
        {
            "symbol": symbol,
            "title": title,
            "site": "Reuters",
            "url": f"https://example.test/{title.replace(' ', '-').lower()}",
            "publishedDate": published_at.isoformat(),
            "text": text,
            "body": body,
        }
    )


def test_default_generator_builder_requires_managed_fmp_provider():
    provider = FakeStockNews()

    assert not any(
        isinstance(generator, NewsGenerator)
        for generator in build_known_generators()
    )

    generators = build_known_generators(fmp=provider)
    news_generators = [
        generator
        for generator in generators
        if isinstance(generator, NewsGenerator)
    ]
    assert len(news_generators) == 1


async def test_holding_match_emits_news_card_with_context_and_magnitude():
    provider = FakeStockNews(
        [
            _news(
                "AAPL unveils new chip roadmap",
                datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
            )
        ]
    )
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL", "0.60")))

    assert provider.calls[0].symbols == ["AAPL"]
    assert provider.calls[0].since == datetime(
        2026, 5, 30, 16, 0, tzinfo=timezone.utc
    )
    assert provider.calls[0].limit == 100
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.event_type == "news"
    assert candidate.related_symbols == ["AAPL"]
    assert candidate.magnitude_score == 0.575
    card = candidate.card
    assert isinstance(card, NewsCard)
    assert card.symbol == "AAPL"
    assert card.headline == "AAPL unveils new chip roadmap"
    assert card.summary == "Digestible summary"
    assert card.related_symbols == ["AAPL"]
    assert card.card_context["symbol"] == "AAPL"
    assert card.card_context["headline"] == "AAPL unveils new chip roadmap"


async def test_no_match_drops_headline():
    provider = FakeStockNews(
        [
            _news(
                "MSFT announces new AI tools",
                datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
                symbol="MSFT",
            )
        ]
    )
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert candidates == []


@pytest.mark.parametrize(
    "exc",
    [
        MarketDataError("unsupported symbol", symbol="AAPL"),
        MarketDataUnavailableError("network unavailable", symbol="AAPL"),
        MarketDataUpstreamError("upstream failed", status_code=503),
    ],
)
async def test_market_data_failures_degrade_to_empty_candidates(exc: Exception):
    provider = FakeStockNews(exc=exc)
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert candidates == []


async def test_summary_falls_back_to_first_200_body_chars():
    provider = FakeStockNews(
        [
            _news(
                "AAPL publishes long update",
                datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
                text=None,
                body="x" * 250,
            )
        ]
    )
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert candidates[0].card.summary == "x" * 200


async def test_missing_summary_and_body_keeps_empty_summary():
    provider = FakeStockNews(
        [
            _news(
                "AAPL publishes short update",
                datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
                text=None,
                body=None,
            )
        ]
    )
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert candidates[0].card.summary == ""


async def test_dedupe_cluster_keeps_earlier_published_headline():
    earlier = _news(
        "AAPL shares rise after product update",
        datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )
    later_duplicate = _news(
        "AAPL shares rise product update after",
        datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc),
    )
    unrelated_newer = _news(
        "AAPL supplier outlook improves",
        datetime(2026, 5, 31, 15, 0, tzinfo=timezone.utc),
    )
    provider = FakeStockNews([later_duplicate, unrelated_newer, earlier])
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert [candidate.card.headline for candidate in candidates] == [
        "AAPL supplier outlook improves",
        "AAPL shares rise after product update",
    ]


async def test_recency_cutoff_drops_items_older_than_24_hours():
    provider = FakeStockNews(
        [
            _news(
                "AAPL older item",
                datetime(2026, 5, 30, 15, 59, 59, tzinfo=timezone.utc),
            ),
            _news(
                "AAPL exactly at cutoff",
                datetime(2026, 5, 30, 16, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert [candidate.card.headline for candidate in candidates] == [
        "AAPL exactly at cutoff"
    ]


async def test_caps_at_five_after_dedupe_ranked_newest_first():
    items = [
        _news(
            f"AAPL item {index}",
            datetime(2026, 5, 31, 10 + index, 0, tzinfo=timezone.utc),
        )
        for index in range(6)
    ]
    provider = FakeStockNews(items)
    generator = NewsGenerator(fmp=provider, now=lambda: NOW)

    candidates = await generator.generate(_ctx(_holding("AAPL")))

    assert [candidate.card.headline for candidate in candidates] == [
        "AAPL item 5",
        "AAPL item 4",
        "AAPL item 3",
        "AAPL item 2",
        "AAPL item 1",
    ]
