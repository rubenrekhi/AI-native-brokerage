"""Integration tests for SEV-565 — agent loop dispatches multiple ``tool_use``
blocks from a single Anthropic response **in parallel**.

The loop must, on a multi-``tool_use`` response:

* Run every per-tool coroutine concurrently (wall-clock ≈ ``max(t_i)``,
  not ``sum(t_i)``).
* Preserve tool_use input order in the persisted follow-up user message
  (``tool_result_blocks``) — Anthropic correlates by ``tool_use_id`` but
  the audit trail / replay depends on stable ordering.
* Persist a ``tool_executions`` row for **every** ``tool_use`` block,
  including the case where an earlier-in-order tool fails (so the audit
  trail stays complete; earlier serial behaviour short-circuited on the
  first failure and skipped later blocks).

Tests run ``run_agent_turn`` against the real local Postgres with a
mocked Anthropic client that scripts each iteration. We assert on
``tool_executions`` and ``model_invocations.request_messages`` rather
than on in-memory state because those JSONB rows are the source of truth
for downstream replay.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    TextBlock as AnthropicTextBlock,
    TextDelta as AnthropicTextDelta,
    ToolUseBlock,
    Usage,
)
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.db import make_session_factory
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import ModelConfig
from app.ai.tools import (
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import Event
from app.models.agent_turn import AgentTurn
from app.models.model_invocation import ModelInvocation
from app.models.tool_execution import ToolExecution
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-parallel-dispatch")


# ---------- fake tools with overlap tracking ----------


class _OverlapTracker:
    """Records per-tool monotonic start/end timestamps.

    Two intervals overlap iff ``a.start < b.end`` and ``b.start < a.end``
    — the canonical interval-intersection test. Used to assert that the
    loop actually ran the tool coroutines concurrently rather than just
    happening to fit under the wall-clock threshold by luck on a fast
    machine.
    """

    def __init__(self) -> None:
        self.starts: dict[str, float] = {}
        self.ends: dict[str, float] = {}

    def overlaps(self, key_a: str, key_b: str) -> bool:
        return (
            self.starts[key_a] < self.ends[key_b]
            and self.starts[key_b] < self.ends[key_a]
        )


class _SleepInput(BaseModel):
    seconds: float


def _make_sleep_tool(
    *,
    name: str,
    sleep_seconds: float,
    tracker: _OverlapTracker,
    key: str,
) -> Tool[_SleepInput]:
    """Build a tool that sleeps ``sleep_seconds`` and records its start/end
    via ``tracker``. The tracker is shared across siblings so the test
    can verify execution windows overlapped.
    """

    class _SleepTool(Tool[_SleepInput]):
        name: ClassVar[str] = ""
        description: ClassVar[str] = "Sleep then return."
        Input: ClassVar[type[BaseModel]] = _SleepInput

        async def execute(
            self, input: _SleepInput, ctx: ToolContext
        ) -> ToolResult:
            tracker.starts[key] = time.monotonic()
            await asyncio.sleep(sleep_seconds)
            tracker.ends[key] = time.monotonic()
            return ToolResult(
                model_payload={"slept": sleep_seconds, "tool": key},
                internal_trace={"key": key},
            )

    _SleepTool.name = name  # type: ignore[misc]
    return _SleepTool()


class _BoomInput(BaseModel):
    pass


class _BoomTool(Tool[_BoomInput]):
    name: ClassVar[str] = "boom_parallel"
    description: ClassVar[str] = "Always raises."
    Input: ClassVar[type[BaseModel]] = _BoomInput

    async def execute(self, input: _BoomInput, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("kaboom")


# ---------- streaming fakes (copied from test_loop_tool_use shape) ----------


class _FakeStream:
    def __init__(self, events: list[Any], final: Message) -> None:
        self._events = events
        self._index = 0
        self._final = final

    def __aiter__(self) -> "_FakeStream":
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def get_final_message(self) -> Message:
        return self._final

    async def close(self) -> None:
        return None


class _FakeStreamManager:
    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _FakeStream:
        return self._stream

    async def __aexit__(self, *exc: Any) -> None:
        await self._stream.close()


def _events_for(message: Message) -> list[Any]:
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            start_block: Any = AnthropicTextBlock(
                text="", type="text", citations=None
            )
        else:
            start_block = block
        events.append(
            RawContentBlockStartEvent(
                content_block=start_block,
                index=index,
                type="content_block_start",
            )
        )
        if block.type == "text" and block.text:
            events.append(
                RawContentBlockDeltaEvent(
                    delta=AnthropicTextDelta(text=block.text, type="text_delta"),
                    index=index,
                    type="content_block_delta",
                )
            )
        events.append(
            RawContentBlockStopEvent(index=index, type="content_block_stop")
        )
    return events


def _stub_client(responses: list[Message]) -> AsyncMock:
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    managers = [
        _FakeStreamManager(_FakeStream(_events_for(r), r)) for r in responses
    ]
    client.messages.stream = MagicMock(side_effect=managers)
    return client


def _multi_tool_use_response(
    *, blocks: list[tuple[str, str, dict[str, Any]]]
) -> Message:
    """Build an assistant ``Message`` with N ``tool_use`` blocks.

    ``blocks`` is a list of ``(tool_name, tool_use_id, input)`` triples.
    Order in the list matches the order Anthropic emitted — the loop's
    ``response.content`` iteration relies on this for input-order
    preservation.
    """
    return Message(
        id=f"msg_parallel_{uuid.uuid4().hex[:8]}",
        content=[
            ToolUseBlock(
                id=tool_use_id,
                name=tool_name,
                input=tool_input,
                type="tool_use",
            )
            for tool_name, tool_use_id, tool_input in blocks
        ],
        model=MODEL_ID,
        role="assistant",
        stop_reason="tool_use",
        type="message",
        usage=Usage(input_tokens=20, output_tokens=8),
    )


def _text_response(*, text_value: str) -> Message:
    return Message(
        id=f"msg_text_{text_value[:6]}",
        content=[AnthropicTextBlock(text=text_value, type="text")],
        model=MODEL_ID,
        role="assistant",
        stop_reason="end_turn",
        type="message",
        usage=Usage(input_tokens=30, output_tokens=12),
    )


# ---------- DB fixture (mirrors test_loop_tool_use) ----------


class _Fixture:
    def __init__(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, engine
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.engine = engine

    async def cleanup(self) -> None:
        async with AsyncSession(
            bind=self.engine, expire_on_commit=False
        ) as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM tool_executions WHERE model_invocation_id IN ("
                    "SELECT id FROM model_invocations WHERE agent_turn_id IN ("
                    "SELECT id FROM agent_turns WHERE conversation_id = :id))"
                ),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text(
                    "DELETE FROM model_invocations WHERE agent_turn_id IN ("
                    "SELECT id FROM agent_turns WHERE conversation_id = :id)"
                ),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM agent_turns WHERE conversation_id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM messages WHERE conversation_id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM conversations WHERE id = :id"),
                {"id": self.conversation_id},
            )
            await cleanup.execute(
                text("DELETE FROM user_profiles WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.execute(
                text("DELETE FROM auth.users WHERE id = :id"),
                {"id": self.user_id},
            )
            await cleanup.commit()


@pytest.fixture
async def fixture(db_engine):
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    email = f"parallel-{user_id}@test.local"
    async with AsyncSession(bind=db_engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await setup.commit()
    fix = _Fixture(
        user_id=user_id, conversation_id=conversation_id, engine=db_engine
    )
    try:
        yield fix
    finally:
        await fix.cleanup()


# ---------- helpers ----------


async def _drain(emitter: SSEEmitter) -> list[Event]:
    events: list[Event] = []
    async for event in emitter.iter_events():
        events.append(event)
    return events


async def _run(
    *,
    fixture: _Fixture,
    db_engine,
    client: AsyncMock,
    tool_registry: ToolRegistry,
    user_message: str = "do the thing",
) -> tuple[Any, list[Event]]:
    emitter = SSEEmitter()
    drain_task = asyncio.create_task(_drain(emitter))
    try:
        result = await run_agent_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            user_message=user_message,
            anthropic_client=client,
            db_factory=make_session_factory(db_engine),
            tool_registry=tool_registry,
            http_clients=ToolHttpClients(),
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=HardCaps(),
            langfuse=_NoopLangfuse(),
            environment="test",
            sse_emitter=emitter,
        )
    finally:
        await emitter.close()
    events = await drain_task
    return result, events


# ---------- main concurrency test ----------


class TestParallelDispatchConcurrency:
    async def test_two_tools_in_one_response_run_concurrently(
        self, db_engine, fixture
    ):
        """Two ~0.2s tools in one response: execution windows overlap
        and dispatch wall-clock < ``2 * sleep`` even with overhead.

        Two backstops together rather than relying on wall-clock alone:

        * **Overlap** is the deterministic concurrency proof — true iff
          the per-tool execution intervals intersect. A fast machine
          can't fake this; if the loop were still serial, ``alpha.end <
          beta.start`` (or vice versa) and the overlap check fails.
        * **Wall-clock** is a coarser smoke test sized for SEV-565's
          acceptance number. Sequential dispatch of two 0.2s sleeps is
          ~0.4s + cold-start overhead (~0.55s on a typical dev box);
          parallel lands ~0.2s + overhead (~0.35s). 0.4s splits the two
          regimes cleanly without flaking on event-loop jitter.
        """
        tracker = _OverlapTracker()
        sleep_seconds = 0.2
        tool_alpha = _make_sleep_tool(
            name="sleep_alpha",
            sleep_seconds=sleep_seconds,
            tracker=tracker,
            key="alpha",
        )
        tool_beta = _make_sleep_tool(
            name="sleep_beta",
            sleep_seconds=sleep_seconds,
            tracker=tracker,
            key="beta",
        )
        registry = ToolRegistry()
        registry.register(tool_alpha)
        registry.register(tool_beta)

        iter_1 = _multi_tool_use_response(
            blocks=[
                ("sleep_alpha", "toolu_par_alpha", {"seconds": sleep_seconds}),
                ("sleep_beta", "toolu_par_beta", {"seconds": sleep_seconds}),
            ]
        )
        iter_2 = _text_response(text_value="done both")
        client = _stub_client([iter_1, iter_2])

        wall_start = time.monotonic()
        result, _events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )
        wall_elapsed = time.monotonic() - wall_start

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2

        # Deterministic concurrency proof: both tools' execution windows
        # must intersect. Asserted first so the wall-clock failure mode
        # below can be diagnosed without ambiguity.
        assert tracker.overlaps("alpha", "beta"), (
            f"Tool execution windows did not overlap: "
            f"alpha=[{tracker.starts['alpha']:.3f}, "
            f"{tracker.ends['alpha']:.3f}], "
            f"beta=[{tracker.starts['beta']:.3f}, "
            f"{tracker.ends['beta']:.3f}]"
        )

        # Sequential dispatch would be ≥ 2 * sleep + overhead (≈ 0.55s
        # on a dev box); parallel lands near sleep + overhead (≈ 0.35s).
        # 0.4s splits the two regimes with margin for jitter.
        assert wall_elapsed < 0.4, (
            f"Expected parallel dispatch (~{sleep_seconds}s + overhead) "
            f"but turn took {wall_elapsed:.3f}s."
        )

        # Both tools wrote their audit rows.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            execs = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                    .order_by(ToolExecution.created_at.asc())
                )
            ).scalars().all()
            assert {te.tool_name for te in execs} == {
                "sleep_alpha",
                "sleep_beta",
            }
            assert {te.status for te in execs} == {"success"}


# ---------- ordering test: input order preserved even when sibling finishes first ----------


class TestParallelDispatchPreservesInputOrder:
    async def test_tool_result_blocks_match_tool_use_input_order(
        self, db_engine, fixture
    ):
        """First-in-order tool sleeps longer than second; tool_result
        blocks in the follow-up user message must still appear in input
        order. Anthropic correlates by ``tool_use_id`` so order is not
        strictly required for correctness, but the audit trail and
        replay rely on stable ordering matching the assistant's
        emission.
        """
        tracker = _OverlapTracker()
        # Slow first, fast second — under parallel dispatch ``beta``
        # finishes BEFORE ``alpha``. We assert that the persisted order
        # is nonetheless ``[alpha, beta]`` matching the tool_use input
        # order.
        tool_alpha = _make_sleep_tool(
            name="sleep_alpha_slow",
            sleep_seconds=0.2,
            tracker=tracker,
            key="alpha",
        )
        tool_beta = _make_sleep_tool(
            name="sleep_beta_fast",
            sleep_seconds=0.05,
            tracker=tracker,
            key="beta",
        )
        registry = ToolRegistry()
        registry.register(tool_alpha)
        registry.register(tool_beta)

        iter_1 = _multi_tool_use_response(
            blocks=[
                ("sleep_alpha_slow", "toolu_order_alpha", {"seconds": 0.2}),
                ("sleep_beta_fast", "toolu_order_beta", {"seconds": 0.05}),
            ]
        )
        iter_2 = _text_response(text_value="done both")
        client = _stub_client([iter_1, iter_2])

        result, _events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )
        assert result.terminal_state == "end_turn"

        # Sanity: beta did finish before alpha (otherwise the ordering
        # test isn't actually testing anything).
        assert tracker.ends["beta"] < tracker.ends["alpha"]

        # Iteration 1's follow-up user message — the tool_result blocks
        # the loop appended for iteration 2's Anthropic call. Order
        # must mirror the assistant's tool_use emission, not completion
        # order.
        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            invs = (
                await v.execute(
                    select(ModelInvocation)
                    .join(AgentTurn, ModelInvocation.agent_turn_id == AgentTurn.id)
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                    .order_by(ModelInvocation.iteration_index.asc())
                )
            ).scalars().all()
            assert len(invs) == 2
            iter_2_messages = invs[1].request_messages
            # [user(turn 1), assistant(tool_use), user(tool_result), ...]
            user_tool_result_msg = iter_2_messages[2]
            assert user_tool_result_msg["role"] == "user"
            tool_result_blocks = [
                b
                for b in user_tool_result_msg["content"]
                if b.get("type") == "tool_result"
            ]
            assert [tr["tool_use_id"] for tr in tool_result_blocks] == [
                "toolu_order_alpha",
                "toolu_order_beta",
            ]
            # And the content payload matches the per-tool model_payload.
            assert json.loads(tool_result_blocks[0]["content"]) == {
                "slept": 0.2,
                "tool": "alpha",
            }
            assert json.loads(tool_result_blocks[1]["content"]) == {
                "slept": 0.05,
                "tool": "beta",
            }


# ---------- audit-row completeness when a sibling fails ----------


class TestParallelDispatchWritesAllAuditRowsOnFailure:
    async def test_failure_in_one_tool_still_persists_sibling_audit_row(
        self, db_engine, fixture
    ):
        """SEV-565 changes the prior short-circuit behaviour: when one
        tool fails, sibling tools still run and their audit rows still
        land. This is the audit-completeness tradeoff option (a) from
        the ticket. The turn still terminates with the first-in-order
        error code, but the ``tool_executions`` table records every
        ``tool_use`` block the model emitted.
        """
        tracker = _OverlapTracker()
        # First tool in input order succeeds — exercises the "success
        # row persisted even though sibling failed" path. Second tool
        # raises mid-execute — its TOOL_ERROR is what the turn
        # ultimately terminates on (first error in input order).
        good_tool = _make_sleep_tool(
            name="sleep_good",
            sleep_seconds=0.05,
            tracker=tracker,
            key="good",
        )
        registry = ToolRegistry()
        registry.register(good_tool)
        registry.register(_BoomTool())

        iter_1 = _multi_tool_use_response(
            blocks=[
                ("boom_parallel", "toolu_fail_boom", {}),
                ("sleep_good", "toolu_fail_good", {"seconds": 0.05}),
            ]
        )
        client = _stub_client([iter_1])

        result, _events = await _run(
            db_engine=db_engine,
            fixture=fixture,
            client=client,
            tool_registry=registry,
        )

        # Boom is first in input order, so its TOOL_ERROR wins.
        assert result.terminal_state == "error"

        async with AsyncSession(bind=db_engine, expire_on_commit=False) as v:
            turn = (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == fixture.conversation_id
                    )
                )
            ).scalar_one()
            assert turn.error_code == ErrorCode.TOOL_ERROR.value

            # Both tool_executions rows are durable — the sibling ran
            # despite boom failing (the key change SEV-565 introduces
            # vs. the prior short-circuit behaviour).
            execs = (
                await v.execute(
                    select(ToolExecution)
                    .join(
                        ModelInvocation,
                        ToolExecution.model_invocation_id == ModelInvocation.id,
                    )
                    .join(
                        AgentTurn,
                        ModelInvocation.agent_turn_id == AgentTurn.id,
                    )
                    .where(AgentTurn.conversation_id == fixture.conversation_id)
                )
            ).scalars().all()
            by_name = {te.tool_name: te for te in execs}
            assert set(by_name.keys()) == {"boom_parallel", "sleep_good"}
            assert by_name["boom_parallel"].status == "error"
            assert "kaboom" in (by_name["boom_parallel"].error_message or "")
            assert by_name["sleep_good"].status == "success"
            assert by_name["sleep_good"].output_payload == {
                "slept": 0.05,
                "tool": "good",
            }
