from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.digest import DigestSnapshot
from app.services.digest.cards import (
    BigMoveCard,
    EarningsResultCard,
    MarketContextCard,
    NewsCard,
)
from app.services.digest.reranker import DigestReranker, RerankResult
from app.services.digest.service import DigestService
from app.services.digest.types import CardCandidate, DigestContext, MarketState


def _ctx() -> DigestContext:
    return DigestContext(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        portfolio_snapshot={"equity": "1000"},
        holdings=[
            {"symbol": "AAPL", "name": "Apple", "market_value": "700"},
            {"symbol": "MSFT", "name": "Microsoft", "market_value": "300"},
        ],
        financial_profile=None,
        market_state=MarketState(
            as_of=datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc),
            session="pre",
        ),
    )


def _market_card(index: int, magnitude: float = 1.0) -> CardCandidate:
    card = MarketContextCard(
        direction="up",
        sp500_change_pct=Decimal("0.01"),
        nasdaq_change_pct=Decimal("0.02"),
        summary=f"Market context {index}",
    )
    return CardCandidate(
        card=card,
        event_type="market_context",
        magnitude_score=magnitude,
        dedupe_key=f"market:{index}",
    )


def _big_move(symbol: str = "AAPL") -> CardCandidate:
    card = BigMoveCard(
        symbol=symbol,
        name=symbol,
        prev_close=Decimal("100"),
        current=Decimal("105"),
        change_abs=Decimal("5"),
        change_pct=Decimal("0.05"),
        related_symbols=[symbol],
    )
    return CardCandidate(
        card=card,
        event_type="big_move",
        magnitude_score=5,
        related_symbols=[symbol],
        dedupe_key=f"big_move:{symbol}",
    )


def _news(symbol: str = "AAPL") -> CardCandidate:
    card = NewsCard(
        symbol=symbol,
        headline=f"{symbol} launches new chip",
        source="Wire",
        url="https://example.com/aapl",
        published_at=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        summary="A factual company update.",
        related_symbols=[symbol],
    )
    return CardCandidate(
        card=card,
        event_type="news",
        magnitude_score=1,
        related_symbols=[symbol],
        dedupe_key=f"news:{symbol}",
    )


def _earnings(symbol: str = "AAPL") -> CardCandidate:
    card = EarningsResultCard(
        symbol=symbol,
        name=symbol,
        grade="A",
        eps_actual=Decimal("1.20"),
        eps_estimate=Decimal("1.00"),
        rev_actual=Decimal("120"),
        rev_estimate=Decimal("100"),
        related_symbols=[symbol],
    )
    return CardCandidate(
        card=card,
        event_type="earnings_result",
        magnitude_score=1,
        related_symbols=[symbol],
        dedupe_key=f"earnings:{symbol}",
    )


def _anthropic_response(ids: list[uuid.UUID] | str) -> SimpleNamespace:
    text = (
        ids
        if isinstance(ids, str)
        else json.dumps([str(card_id) for card_id in ids])
    )
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


async def test_reranker_returns_llm_ordered_card_ids():
    candidates = [_market_card(index) for index in range(8)]
    expected = [candidate.card.id for candidate in candidates[4:0:-1]]
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    anthropic.messages.create.return_value = _anthropic_response(expected)

    ranked = await DigestReranker(anthropic, model="test-model").rank(
        candidates, _ctx()
    )

    assert ranked == expected
    kwargs = anthropic.messages.create.await_args.kwargs
    assert kwargs["model"] == "test-model"
    assert "ordered JSON array" in kwargs["system"]


async def test_reranker_prompt_sends_top_holdings_sorted_with_pct_weights():
    ctx = DigestContext(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        portfolio_snapshot={"equity": "1000"},
        holdings=[
            {"symbol": "SMALL", "name": "Small", "market_value": "50"},
            {"symbol": "BIG", "name": "Big", "market_value": "700"},
            {"symbol": "MID", "name": "Mid", "portfolio_weight": "25%"},
        ],
        financial_profile=None,
        market_state=MarketState(
            as_of=datetime(2026, 5, 29, 13, 0, tzinfo=timezone.utc),
            session="pre",
        ),
    )
    candidates = [_market_card(index) for index in range(3)]
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    anthropic.messages.create.return_value = _anthropic_response(
        [candidate.card.id for candidate in candidates]
    )

    await DigestReranker(anthropic, model="test-model").rank(candidates, ctx)

    content = anthropic.messages.create.await_args.kwargs["messages"][0]["content"]
    holdings = json.loads(content)["top_10_holdings"]
    assert [(holding["symbol"], holding["weight_pct"]) for holding in holdings] == [
        ("BIG", "70.00"),
        ("MID", "25.00"),
        ("SMALL", "5.00"),
    ]


async def test_reranker_falls_back_to_heuristic_order_on_invalid_output():
    candidates = [_market_card(index, magnitude=float(index)) for index in range(5)]
    heuristic = list(reversed(candidates))
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    anthropic.messages.create.return_value = _anthropic_response(
        "Use the first cards."
    )

    ranked = await DigestReranker(anthropic).rank(
        candidates, _ctx(), fallback_order=heuristic
    )

    assert ranked == [candidate.card.id for candidate in heuristic]


async def test_reranker_metadata_marks_fallback_and_adds_breadcrumb(monkeypatch):
    candidates = [_market_card(index, magnitude=float(index)) for index in range(5)]
    heuristic = list(reversed(candidates))
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))
    anthropic.messages.create.return_value = _anthropic_response("not json")
    breadcrumbs = []
    monkeypatch.setattr(
        "app.services.digest.reranker.sentry_sdk.add_breadcrumb",
        lambda **kwargs: breadcrumbs.append(kwargs),
    )

    result = await DigestReranker(anthropic).rank_with_metadata(
        candidates, _ctx(), fallback_order=heuristic
    )

    assert result.ordered_ids == [candidate.card.id for candidate in heuristic]
    assert result.used_fallback is True
    assert result.fallback_reason == "invalid_json"
    assert breadcrumbs == [
        {
            "category": "digest.reranker",
            "message": "fallback_to_heuristic_order",
            "level": "warning",
            "data": {"reason": "invalid_json"},
        }
    ]


async def test_reranker_fallback_excludes_prescriptive_card_copy():
    candidates = [_market_card(index) for index in range(3)]
    candidates[0].card.summary = "You should buy more AAPL."
    anthropic = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))

    ranked = await DigestReranker(anthropic).rank(candidates, _ctx())

    assert ranked == [candidate.card.id for candidate in candidates[1:]]
    anthropic.messages.create.assert_not_called()


async def test_generate_for_user_continues_after_generator_failure(monkeypatch):
    ctx = _ctx()

    class FailingGenerator:
        async def generate(self, *_args):
            raise RuntimeError("boom")

    class WorkingGenerator:
        async def generate(self, *_args):
            return [_market_card(1)]

    async def fake_build_context(*_args):
        return ctx

    async def fake_upsert(_db, snapshot):
        return snapshot

    monkeypatch.setattr(
        "app.services.digest.service.build_context", fake_build_context
    )
    monkeypatch.setattr(
        "app.services.digest.service.DigestRepository.upsert", fake_upsert
    )

    service = DigestService(
        AsyncMock(),
        alpaca=AsyncMock(),
        generators=[FailingGenerator(), WorkingGenerator()],
    )
    snapshot = await service.generate_for_user(ctx.user_id)

    assert [card["kind"] for card in snapshot.cards] == ["market_context"]
    assert snapshot.cards[0]["priority"] == 1


async def test_generate_for_user_emits_generator_and_overall_logs(monkeypatch):
    ctx = _ctx()
    events = []

    class FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

    class WorkingGenerator:
        async def generate(self, *_args):
            return [_market_card(1)]

    async def fake_build_context(*_args):
        return ctx

    async def fake_upsert(_db, snapshot):
        return snapshot

    monkeypatch.setattr("app.services.digest.service.logger", FakeLogger())
    monkeypatch.setattr(
        "app.services.digest.service.build_context", fake_build_context
    )
    monkeypatch.setattr(
        "app.services.digest.service.DigestRepository.upsert", fake_upsert
    )

    service = DigestService(
        AsyncMock(),
        alpaca=AsyncMock(),
        generators=[WorkingGenerator()],
    )

    await service.generate_for_user(ctx.user_id)

    generator_log = next(
        kwargs for event, kwargs in events if event == "digest.generator.completed"
    )
    overall_log = next(
        kwargs for event, kwargs in events if event == "digest.generation.completed"
    )
    assert generator_log["name"] == "WorkingGenerator"
    assert generator_log["candidate_count"] == 1
    assert generator_log["error"] is None
    assert overall_log["user_id"] == str(ctx.user_id)
    assert overall_log["final_card_count"] == 1
    assert overall_log["card_kinds"] == ["market_context"]
    assert overall_log["persisted"] is True


async def test_preview_for_user_runs_pipeline_without_upsert(monkeypatch):
    ctx = _ctx()

    class WorkingGenerator:
        async def generate(self, *_args):
            return [_market_card(1)]

    async def fake_build_context(*_args):
        return ctx

    async def fail_upsert(*_args):
        raise AssertionError("preview_for_user must not persist")

    monkeypatch.setattr(
        "app.services.digest.service.build_context", fake_build_context
    )
    monkeypatch.setattr(
        "app.services.digest.service.DigestRepository.upsert", fail_upsert
    )

    service = DigestService(
        AsyncMock(),
        alpaca=AsyncMock(),
        generators=[WorkingGenerator()],
    )

    snapshot = await service.preview_for_user(ctx.user_id)

    assert [card["kind"] for card in snapshot.cards] == ["market_context"]
    assert snapshot.id is None


async def test_generate_for_user_requires_provider_clients_without_injected_generators(
    monkeypatch,
):
    ctx = _ctx()

    async def fake_build_context(*_args):
        return ctx

    monkeypatch.setattr(
        "app.services.digest.service.build_context", fake_build_context
    )

    service = DigestService(AsyncMock(), alpaca=AsyncMock())

    try:
        await service.generate_for_user(ctx.user_id)
    except RuntimeError as exc:
        assert "market_data and fmp clients" in str(exc)
    else:
        raise AssertionError("expected provider dependency failure")


async def test_cross_generator_enrichment_populates_reason_and_reaction(monkeypatch):
    ctx = _ctx()
    big_move = _big_move("AAPL")
    news = _news("AAPL")
    earnings = _earnings("AAPL")

    class Generator:
        async def generate(self, *_args):
            return [big_move, news, earnings]

    class OrderedReranker:
        async def rank_with_metadata(self, candidates, *_args, **_kwargs):
            return RerankResult(
                ordered_ids=[candidate.card.id for candidate in candidates],
                used_fallback=False,
            )

    async def fake_build_context(*_args):
        return ctx

    async def fake_upsert(_db, snapshot: DigestSnapshot):
        return snapshot

    monkeypatch.setattr(
        "app.services.digest.service.build_context", fake_build_context
    )
    monkeypatch.setattr(
        "app.services.digest.service.DigestRepository.upsert", fake_upsert
    )

    service = DigestService(
        AsyncMock(),
        alpaca=AsyncMock(),
        generators=[Generator()],
        reranker=OrderedReranker(),
    )
    snapshot = await service.generate_for_user(ctx.user_id)

    cards = {card["kind"]: card for card in snapshot.cards}
    assert cards["big_move"]["reason"] == "AAPL launches new chip"
    assert Decimal(cards["earnings_result"]["stock_reaction_pct"]) == Decimal(
        "0.05"
    )
