"""Smoke case: ``"say hello"`` against the real Anthropic API (B4.2).

End-to-end happy path through the SSE chat-turn endpoint:

1. POST ``/v1/conversations/{id}/turns`` with ``"say hello"``.
2. Parse the SSE stream and confirm the wire envelope: a
   ``turn_started`` opener, at least one ``text_delta`` carrying
   non-empty content, and a ``turn_completed`` closer.
3. Verify the persisted ``agent_turns`` row records a positive cost,
   ``terminal_state='end_turn'``, and ``iterations_count == 1``.

The test is gated by ``RUN_AI_SMOKE=1`` and the prerequisites enforced
by ``conftest.py:_smoke_prereqs``. The session-scoped
``_smoke_model_override`` fixture pins the run to ``MODELS.MAIN`` (the
prod model) — Haiku doesn't support the adaptive thinking the runtime requests.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import httpx_sse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.transport.events import (
    Event,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)
from app.models.agent_turn import AgentTurn
from tests.ai.smoke.conftest import parse_sse_event

# ~10s budget per the plan acceptance for B4.2; the asyncio.wait_for
# below enforces it. Real Haiku turns for a one-word prompt land in
# 2-5s, so the margin tolerates streaming jitter without masking a
# regression that genuinely slows things down.
_REQUEST_TIMEOUT_S = 10.0


async def _consume_stream(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
) -> list[Event]:
    """Stream the endpoint and return the parsed event sequence.

    ``aconnect_sse`` opens the response, iterates ``ServerSentEvent``
    objects, and ``parse_sse_event`` round-trips them through the wire
    parser — any drift between the server's ``id``/``event`` lines and
    the JSON body fails loudly here, mirroring the cross-check the
    integration tests do.
    """
    events: list[Event] = []
    async with httpx_sse.aconnect_sse(
        client, "POST", url, json=body
    ) as event_source:
        async for sse in event_source.aiter_sse():
            events.append(parse_sse_event(sse))
    return events


async def test_hello_streams_text_and_records_cost(
    db_engine,
    smoke_user: uuid.UUID,
    smoke_conversation_id: uuid.UUID,
    smoke_client: httpx.AsyncClient,
) -> None:
    url = f"/v1/conversations/{smoke_conversation_id}/turns"
    body = {
        "message": "say hello",
        "idempotency_key": f"smoke-hello-{uuid.uuid4()}",
    }

    events = await asyncio.wait_for(
        _consume_stream(smoke_client, url, body),
        timeout=_REQUEST_TIMEOUT_S,
    )

    # Wire envelope: opener, at least one text_delta with content, closer.
    assert events, "expected SSE events from real Anthropic call"
    assert isinstance(events[0], TurnStarted), (
        f"expected first event TurnStarted, got {type(events[0]).__name__}"
    )
    assert events[0].conversation_id == smoke_conversation_id

    text_deltas = [e for e in events if isinstance(e, TextDelta)]
    assert text_deltas, "expected at least one text_delta"
    assert any(d.text.strip() for d in text_deltas), (
        "expected at least one text_delta with non-empty content"
    )

    assert isinstance(events[-1], TurnCompleted), (
        f"expected last event TurnCompleted, got {type(events[-1]).__name__}"
    )
    completed = events[-1]
    assert completed.terminal_state == "end_turn"
    assert completed.iterations_count == 1
    assert completed.total_cost_usd_micros > 0, (
        "expected positive cost on turn_completed"
    )

    # DB cross-check: the persisted agent_turns row should mirror the
    # turn_completed payload — same iteration count, same positive cost,
    # and a recorded error_code of NULL.
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
        turn = (
            await v.execute(
                select(AgentTurn).where(
                    AgentTurn.conversation_id == smoke_conversation_id
                )
            )
        ).scalar_one()
        assert turn.terminal_state == "end_turn"
        assert turn.error_code is None
        assert turn.iterations_count == 1
        assert turn.total_cost_usd_micros > 0
        assert turn.assistant_message_id is not None
