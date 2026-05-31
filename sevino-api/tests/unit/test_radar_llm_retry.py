"""End-to-end `RadarLLM.pick` flow over a mocked Anthropic client:
one corrective retry, offender-dropping, and the raise path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from anthropic import APIConnectionError

from app.services.radar_job import RadarJobError
from app.services.radar_job.candidate_sourcer import Candidate
from app.services.radar_job.llm import TOOL_NAME, RadarLLM, UserContext


def _pool() -> list[Candidate]:
    specs = [
        ("AAPL", "Apple", "Technology", "owned_sector"),
        ("MSFT", "Microsoft", "Technology", "owned_sector"),
        ("XOM", "Exxon", "Energy", "diversification"),
        ("DUK", "Duke Energy", "Utilities", "diversification"),
        ("JPM", "JPMorgan", "Financials", "upcoming_event"),
        ("KO", "Coca-Cola", "Staples", "upcoming_event"),
        ("BRK.B", "Berkshire", "Financials", "broad_notable"),
    ]
    return [
        Candidate(symbol=s, name=n, sector=sec, market_cap=10_000_000_000, bucket=b)
        for s, n, sec, b in specs
    ]


def _pick(symbol, bucket, label="A widely-followed large-cap name", relevance=0.7):
    return {"symbol": symbol, "label": label, "bucket": bucket, "relevance": relevance}


_VALID_FIVE = [
    _pick("AAPL", "owned_sector"),
    _pick("XOM", "diversification"),
    _pick("DUK", "diversification"),
    _pick("JPM", "upcoming_event"),
    _pick("BRK.B", "broad_notable"),
]


def _tool_response(picks: list[dict]):
    block = SimpleNamespace(type="tool_use", name=TOOL_NAME, input={"picks": picks})
    return SimpleNamespace(content=[block])


def _text_response():
    return SimpleNamespace(content=[SimpleNamespace(type="text", text="no tool")])


def _client(*responses):
    client = SimpleNamespace(messages=SimpleNamespace())
    client.messages.create = AsyncMock(side_effect=list(responses))
    return client


def _ctx():
    return UserContext(risk_tolerance="moderate", age=30, goals=["growth"])


async def test_clean_first_response_returns_without_retry():
    client = _client(_tool_response(_VALID_FIVE))
    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert len(picks) == 5
    assert client.messages.create.await_count == 1


async def test_prescriptive_first_response_then_clean_retry():
    bad = [_pick("AAPL", "owned_sector", label="Great buy right now")] + _VALID_FIVE[1:]
    client = _client(_tool_response(bad), _tool_response(_VALID_FIVE))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert client.messages.create.await_count == 2
    assert {p.symbol for p in picks} == {"AAPL", "XOM", "DUK", "JPM", "BRK.B"}


async def test_schema_invalid_first_response_then_clean_retry():
    client = _client(_tool_response(_VALID_FIVE[:3]), _tool_response(_VALID_FIVE))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert client.messages.create.await_count == 2
    assert len(picks) == 5


async def test_missing_tool_use_first_response_then_clean_retry():
    client = _client(_text_response(), _tool_response(_VALID_FIVE))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert client.messages.create.await_count == 2
    assert len(picks) == 5


async def test_retry_drops_offenders_when_five_valid_remain():
    # Retry returns 7 picks, one hallucinated — 6 valid survive, offender dropped.
    retry = _VALID_FIVE + [
        _pick("MSFT", "owned_sector"),
        _pick("FAKE", "broad_notable"),
    ]
    client = _client(_tool_response(_VALID_FIVE[:3]), _tool_response(retry))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert len(picks) == 6
    assert "FAKE" not in {p.symbol for p in picks}


async def test_raises_when_retry_leaves_fewer_than_five_valid():
    # Retry has 5 picks but 2 are prescriptive → only 3 valid remain.
    retry = [
        _pick("AAPL", "owned_sector", label="You should buy"),
        _pick("MSFT", "owned_sector", label="Must own this"),
        _pick("XOM", "diversification"),
        _pick("JPM", "upcoming_event"),
        _pick("BRK.B", "broad_notable"),
    ]
    client = _client(_tool_response(_VALID_FIVE[:3]), _tool_response(retry))

    with pytest.raises(RadarJobError) as exc:
        await RadarLLM(client).pick(_pool(), _ctx())
    assert exc.value.code == "llm_validation_failed"


async def test_raises_when_retry_also_missing_tool_use():
    client = _client(_text_response(), _text_response())

    with pytest.raises(RadarJobError):
        await RadarLLM(client).pick(_pool(), _ctx())


async def test_returned_symbol_is_canonicalized_to_pool_casing():
    lowered = [{**p, "symbol": p["symbol"].lower()} for p in _VALID_FIVE]
    client = _client(_tool_response(lowered))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert {p.symbol for p in picks} == {"AAPL", "XOM", "DUK", "JPM", "BRK.B"}


async def test_duplicate_symbol_in_clean_response_triggers_retry():
    # AAPL appears twice; the repeat is flagged so the first response is not
    # accepted, and the clean retry collapses it to a single pick.
    dupes = [_pick("AAPL", "owned_sector")] + _VALID_FIVE
    client = _client(_tool_response(dupes), _tool_response(_VALID_FIVE))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    assert client.messages.create.await_count == 2
    symbols = [p.symbol for p in picks]
    assert len(symbols) == len(set(symbols))
    assert len(picks) == 5


async def test_retry_drops_duplicate_symbol_when_five_valid_remain():
    retry = _VALID_FIVE + [_pick("AAPL", "owned_sector"), _pick("MSFT", "owned_sector")]
    client = _client(_tool_response(_VALID_FIVE[:3]), _tool_response(retry))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    symbols = [p.symbol for p in picks]
    assert symbols.count("AAPL") == 1
    assert len(symbols) == len(set(symbols))


async def test_picks_returned_in_relevance_order():
    scored = [
        _pick("AAPL", "owned_sector", relevance=0.2),
        _pick("XOM", "diversification", relevance=0.9),
        _pick("DUK", "diversification", relevance=0.5),
        _pick("JPM", "upcoming_event", relevance=0.7),
        _pick("BRK.B", "broad_notable", relevance=0.1),
    ]
    client = _client(_tool_response(scored))

    picks = await RadarLLM(client).pick(_pool(), _ctx())

    relevances = [p.relevance for p in picks]
    assert relevances == sorted(relevances, reverse=True)


async def test_provider_error_raises_radar_job_error():
    client = SimpleNamespace(messages=SimpleNamespace())
    client.messages.create = AsyncMock(
        side_effect=APIConnectionError(
            request=httpx.Request("POST", "https://api.anthropic.com")
        )
    )

    with pytest.raises(RadarJobError) as exc:
        await RadarLLM(client).pick(_pool(), _ctx())
    assert exc.value.code == "llm_provider_error"
