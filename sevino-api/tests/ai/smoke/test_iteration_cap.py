"""Smoke case: iteration cap breach (B4.3).

Surfaces the cap mechanism end-to-end through the SSE endpoint:

1. Override ``get_hard_caps`` so the route resolves to
   ``HardCaps(max_iterations=0)``.
2. POST a real chat turn — the loop's first cap check breaches before
   any Anthropic call, so the run is deterministic and bills nothing.
3. Confirm the wire emits ``turn_started`` followed by an ``error``
   frame with ``code=turn_iteration_limit``.
4. Confirm the persisted ``agent_turns`` row carries
   ``terminal_state='iteration_limit'`` and matching ``error_code``.

Why ``max_iterations=0`` rather than the plan's nominal ``=2``:
without tools, Claude returns ``end_turn`` on iteration 0 and never
re-enters the loop, so ``=2`` cannot be tripped via real Anthropic in
v0. ``=0`` exercises the same cap-breach code path with a deterministic
trigger and zero token spend — sufficient for "surfaces the cap
mechanism end-to-end" (B4.3 acceptance) and aligned with the unit /
integration tests that already use this trick.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import httpx
import httpx_sse
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.runtime.caps import HardCaps, get_hard_caps
from app.ai.runtime.errors import ErrorCode
from app.ai.transport.events import Error, Event, TurnStarted
from app.main import app
from app.models.agent_turn import AgentTurn
from tests.ai.smoke.conftest import parse_sse_event

# Cap breach short-circuits before any Anthropic call so 5s is plenty.
_REQUEST_TIMEOUT_S = 5.0


@pytest.fixture
def hard_caps_zero() -> Iterator[None]:
    """Install ``HardCaps(max_iterations=0)`` for the duration of the test."""
    app.dependency_overrides[get_hard_caps] = (
        lambda: HardCaps(max_iterations=0)
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_hard_caps, None)


async def _consume_stream(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
) -> list[Event]:
    events: list[Event] = []
    async with httpx_sse.aconnect_sse(
        client, "POST", url, json=body
    ) as event_source:
        async for sse in event_source.aiter_sse():
            events.append(parse_sse_event(sse))
    return events


async def test_iteration_cap_emits_error_and_persists_terminal_state(
    db_engine,
    hard_caps_zero,
    smoke_user: uuid.UUID,
    smoke_conversation_id: uuid.UUID,
    smoke_client: httpx.AsyncClient,
) -> None:
    url = f"/v1/conversations/{smoke_conversation_id}/turns"
    body = {
        # A prompt that *would* tempt Claude to call tools, recorded for
        # readability — the cap breach short-circuits before the model
        # is asked, so the prompt content does not affect the outcome.
        "message": "What's the latest AAPL price?",
        "idempotency_key": f"smoke-iter-cap-{uuid.uuid4()}",
    }

    events = await asyncio.wait_for(
        _consume_stream(smoke_client, url, body),
        timeout=_REQUEST_TIMEOUT_S,
    )

    # Wire envelope: turn_started → error. No text deltas, no
    # turn_completed — the loop never enters its first iteration.
    assert [type(e) for e in events] == [TurnStarted, Error], (
        f"expected [TurnStarted, Error], got "
        f"{[type(e).__name__ for e in events]}"
    )

    started = events[0]
    assert isinstance(started, TurnStarted)
    assert started.conversation_id == smoke_conversation_id

    err = events[1]
    assert isinstance(err, Error)
    assert err.code == ErrorCode.TURN_ITERATION_LIMIT
    # The loop's terminal-frame message is informational; we assert the
    # terminal_state hint rides along so debuggers tracing the wire have
    # something more specific than the code alone.
    assert err.message == "terminal_state=iteration_limit"

    # DB cross-check: the agent_turns row reflects the cap breach and no
    # model_invocation rows were written (no Anthropic call was made).
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
        turn = (
            await v.execute(
                select(AgentTurn).where(
                    AgentTurn.conversation_id == smoke_conversation_id
                )
            )
        ).scalar_one()
        assert turn.terminal_state == "iteration_limit"
        assert turn.error_code == ErrorCode.TURN_ITERATION_LIMIT.value
        assert turn.iterations_count == 0
        assert turn.total_cost_usd_micros == 0
        assert turn.assistant_message_id is None
