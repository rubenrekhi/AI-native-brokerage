"""Unit tests for ``run_agent_turn``.

The agent loop is exercised end-to-end with a fake Anthropic client and a
fake DB factory whose context manager yields a recording stub. Persistence
side-effects are asserted against ``ConversationRepository`` call captures
(the repository itself is integration-tested separately in
``tests/ai/integration/test_conversation_repo.py``).

The loop drives the SSE wire envelope (``turn_started`` → per-block
streams → terminal frame), so every test passes a real :class:`SSEEmitter`
and the helper drains it after the loop returns.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx
import pytest
from anthropic.types import (
    Message,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
    TextBlock,
    TextDelta as AnthropicTextDelta,
    ThinkingBlock,
    ThinkingDelta,
    Usage,
)

from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.cost import cost_usd_micros
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig, ToolRegistry
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Error,
    Event,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)

MODEL_ID = "claude-sonnet-4-6"
SYSTEM_PROMPT = SystemPrompt(text="you are sevino", hash="hash-abc")


# ---------- shared fakes ----------


def _make_response(
    *,
    text: str = "hello",
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    extra_blocks: list[Any] | None = None,
) -> Message:
    """Construct a real ``Message`` so the loop's ``model_dump`` call works."""
    blocks: list[Any] = [TextBlock(text=text, type="text")]
    if extra_blocks:
        blocks.extend(extra_blocks)
    return Message(
        id="msg_1",
        content=blocks,
        model=MODEL_ID,
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _events_for(message: Message) -> list[Any]:
    """Build a stream of raw Anthropic events that, when consumed, would
    accumulate into ``message``.

    The loop only branches on ``content_block_start`` / ``content_block_delta``
    / ``content_block_stop`` for text blocks, so for thinking and other
    blocks we still emit the start/stop bracket (so block-index tracking
    is realistic) but no deltas — matching what the SDK does when the
    final accumulated block is reconstructed in one piece.
    """
    events: list[Any] = []
    for index, block in enumerate(message.content):
        if block.type == "text":
            # ``content_block_start`` for text always carries an empty
            # text and no citations — the body arrives via deltas.
            start_block = TextBlock(text="", type="text", citations=None)
        elif block.type == "thinking":
            start_block = ThinkingBlock(
                thinking="", signature="", type="thinking"
            )
        else:
            # Unknown block shape — pass through so the discriminator
            # validates. Unused by current tests.
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
                    delta=AnthropicTextDelta(
                        text=block.text, type="text_delta"
                    ),
                    index=index,
                    type="content_block_delta",
                )
            )
        elif block.type == "thinking" and block.thinking:
            events.append(
                RawContentBlockDeltaEvent(
                    delta=ThinkingDelta(
                        thinking=block.thinking, type="thinking_delta"
                    ),
                    index=index,
                    type="content_block_delta",
                )
            )
        events.append(
            RawContentBlockStopEvent(
                index=index, type="content_block_stop"
            )
        )
    return events


class _FakeStream:
    """Minimal duck of :class:`anthropic.AsyncMessageStream` covering the
    surface ``run_agent_turn`` consumes: async iteration over raw stream
    events plus a final ``get_final_message()`` call. ``close()`` is a
    no-op since the fake holds no real resources."""

    def __init__(self, events: list[Any], final_message: Message) -> None:
        self._events = events
        self._index = 0
        self._final = final_message

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
    """Async context manager wrapping a :class:`_FakeStream`. Mirrors the
    ``AsyncMessageStreamManager`` shape returned by
    ``anthropic_client.messages.stream(...)``."""

    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> _FakeStream:
        return self._stream

    async def __aexit__(self, *exc: Any) -> None:
        await self._stream.close()


class _RaisingStreamManager:
    """Stream manager that raises in ``__aenter__`` — models an Anthropic
    failure that surfaces before any wire events are received (the SDK
    awaits the API request inside ``__aenter__``)."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def __aenter__(self) -> Any:
        raise self._exc

    async def __aexit__(self, *exc: Any) -> None:
        return None


@dataclass
class _StubSession:
    """Minimal placeholder yielded by the fake db_factory.

    Repository methods are patched at the class level so this object is
    only ever passed through; we never call methods on it directly.
    """


def _make_db_factory() -> Any:
    """Returns a callable matching ``DbSessionFactory`` whose context manager
    yields a ``_StubSession``. Using ``asynccontextmanager`` keeps the call
    site identical to the real factory."""

    @asynccontextmanager
    async def factory():
        yield _StubSession()

    return factory


@pytest.fixture
def repo_mocks(monkeypatch):
    """Patch every ``ConversationRepository`` method the loop calls.

    Returns the dict of mocks so individual tests can inspect call args
    and override return values.
    """
    user_msg_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    assistant_msg_id = uuid.uuid4()

    user_msg = type("M", (), {"id": user_msg_id, "role": "user"})()
    turn = type("T", (), {"id": turn_id})()
    assistant_msg = type("M", (), {"id": assistant_msg_id})()

    mocks = {
        "append_user_message": AsyncMock(return_value=user_msg),
        "load_history": AsyncMock(return_value=[]),
        "start_agent_turn": AsyncMock(return_value=turn),
        "record_model_invocation": AsyncMock(),
        "append_assistant_message": AsyncMock(return_value=assistant_msg),
        "complete_agent_turn": AsyncMock(),
        "_ids": {
            "user_msg_id": user_msg_id,
            "turn_id": turn_id,
            "assistant_msg_id": assistant_msg_id,
        },
    }
    for name in (
        "append_user_message",
        "load_history",
        "start_agent_turn",
        "record_model_invocation",
        "append_assistant_message",
        "complete_agent_turn",
    ):
        monkeypatch.setattr(
            "app.ai.runtime.loop.ConversationRepository." + name, mocks[name]
        )
    return mocks


def _make_client(response_or_exc: Any) -> Any:
    """Build a fake ``AsyncAnthropic`` whose ``messages.stream`` produces
    a manager that streams events accumulating to ``response_or_exc``
    (or raises if it's a ``BaseException``). When a list is passed, each
    call yields a manager streaming the next item — used to exercise
    multi-iteration loops (A1.7)."""

    client = MagicMock(spec=anthropic.AsyncAnthropic)

    def _to_manager(item: Any) -> Any:
        if isinstance(item, BaseException):
            return _RaisingStreamManager(item)
        events = _events_for(item)
        return _FakeStreamManager(_FakeStream(events, item))

    if isinstance(response_or_exc, list):
        managers = [_to_manager(r) for r in response_or_exc]
        client.messages.stream = MagicMock(side_effect=managers)
    else:
        client.messages.stream = MagicMock(
            return_value=_to_manager(response_or_exc)
        )
    return client


async def _drain(emitter: SSEEmitter) -> list[Event]:
    """Collect every event the loop pushed onto ``emitter``.

    The loop closes the emitter only when its own try/finally completes
    successfully; for exception paths the iterator would block waiting
    for the close sentinel. Tests close the emitter themselves after the
    loop returns so iteration is guaranteed to drain.
    """
    events: list[Event] = []
    async for event in emitter.iter_events():
        events.append(event)
    return events


async def _run(
    client: Any,
    repo_mocks: dict[str, Any],
    *,
    hard_caps: HardCaps | None = None,
    tool_registry: ToolRegistry | None = None,
    user_message: str = "hello",
    langfuse: Any = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    emitter: SSEEmitter | None = None,
) -> tuple[Any, list[Event]]:
    """Run the loop and return ``(result, events)``.

    Drives the emitter's iterator concurrently so a fast-emitting loop
    can't fill the queue and deadlock on ``emit``. ``emitter`` defaults
    to a fresh :class:`SSEEmitter`.
    """
    em = emitter or SSEEmitter()
    drain_task = asyncio.create_task(_drain(em))

    try:
        result = await run_agent_turn(
            user_id=user_id or uuid.uuid4(),
            conversation_id=conversation_id or uuid.uuid4(),
            user_message=user_message,
            anthropic_client=client,
            db_factory=_make_db_factory(),
            tool_registry=tool_registry or EMPTY_REGISTRY,
            system_prompt=SYSTEM_PROMPT,
            model_config=ModelConfig(model_id=MODEL_ID),
            hard_caps=hard_caps or HardCaps(),
            langfuse=langfuse if langfuse is not None else _NoopLangfuse(),
            environment="test",
            sse_emitter=em,
        )
    finally:
        await em.close()
    events = await drain_task
    return result, events


# ---------- happy path ----------


class TestHappyPath:
    async def test_single_iteration_returns_expected_result(self, repo_mocks):
        client = _make_client(_make_response(text="hi there"))

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 1
        # Persisted blocks include the server-assigned block_id; assert on
        # the user-visible fields and shape independently of the ULID.
        assert len(result.assistant_message_blocks) == 1
        block = result.assistant_message_blocks[0]
        assert block["type"] == "text"
        assert block["text"] == "hi there"
        assert isinstance(block["block_id"], str) and block["block_id"]
        assert result.total_cost_usd_micros > 0
        client.messages.stream.assert_called_once()

    async def test_persists_user_message_with_text_block(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks, user_message="how is AMD")

        repo_mocks["append_user_message"].assert_awaited_once()
        kwargs = repo_mocks["append_user_message"].call_args.kwargs
        assert kwargs["content_blocks"] == [
            {"type": "text", "text": "how is AMD"}
        ]

    async def test_starts_agent_turn_with_prompt_hash_and_model(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        kwargs = repo_mocks["start_agent_turn"].call_args.kwargs
        assert kwargs["prompt_hash"] == SYSTEM_PROMPT.hash
        assert kwargs["model_id"] == MODEL_ID
        assert kwargs["user_message_id"] == repo_mocks["_ids"]["user_msg_id"]

    async def test_records_model_invocation_with_full_request_response(
        self, repo_mocks
    ):
        response = _make_response(text="answer", input_tokens=42, output_tokens=11)
        client = _make_client(response)

        await _run(client, repo_mocks)

        repo_mocks["record_model_invocation"].assert_awaited_once()
        kwargs = repo_mocks["record_model_invocation"].call_args.kwargs
        assert kwargs["iteration_index"] == 0
        assert kwargs["model_id"] == MODEL_ID
        assert kwargs["request_system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        # The request_messages list is built from history; with empty history
        # plus the just-persisted user message it would be [], because the
        # mocked load_history returns []. The user message is then implicitly
        # in the messages array on the next iteration — but for v0 single
        # iteration, the request goes out with whatever history returned.
        # Asserting structure rather than specific values keeps the test
        # robust against ordering changes.
        assert isinstance(kwargs["request_messages"], list)
        assert kwargs["response_content"] == [
            {"citations": None, "text": "answer", "type": "text"}
        ]
        assert kwargs["stop_reason"] == "end_turn"
        assert kwargs["input_tokens"] == 42
        assert kwargs["output_tokens"] == 11
        assert kwargs["cost_usd_micros"] > 0
        assert kwargs["latency_ms"] is not None

    async def test_completes_agent_turn_with_totals_and_assistant_link(
        self, repo_mocks
    ):
        client = _make_client(
            _make_response(input_tokens=42, output_tokens=11)
        )

        await _run(client, repo_mocks)

        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "end_turn"
        assert kwargs["error_code"] is None
        assert kwargs["assistant_message_id"] == (
            repo_mocks["_ids"]["assistant_msg_id"]
        )
        assert kwargs["iterations_count"] == 1
        assert kwargs["total_input_tokens"] == 42
        assert kwargs["total_output_tokens"] == 11
        assert kwargs["total_thinking_tokens"] == 0
        assert kwargs["total_cost_usd_micros"] > 0

    async def test_persists_assistant_message_with_text_blocks_only(
        self, repo_mocks
    ):
        # Thinking blocks must NOT leak into messages.content_blocks (they
        # stay verbatim in model_invocations.response_content for next-turn
        # roundtripping, but the user-facing message is text-only).
        client = _make_client(
            _make_response(
                text="visible answer",
                extra_blocks=[
                    ThinkingBlock(
                        thinking="hidden reasoning",
                        signature="sig_xyz",
                        type="thinking",
                    ),
                ],
            )
        )

        await _run(client, repo_mocks)

        kwargs = repo_mocks["append_assistant_message"].call_args.kwargs
        assert len(kwargs["content_blocks"]) == 1
        block = kwargs["content_blocks"][0]
        assert block["type"] == "text"
        assert block["text"] == "visible answer"
        assert isinstance(block["block_id"], str) and block["block_id"]


# ---------- SSE wire envelope (B2.4) ----------


class TestSSEWireEnvelope:
    """The loop owns the wire envelope after B2.4. ``turn_started`` fires
    once ``agent_turns.id`` is known; per-block ``block_start`` /
    ``text_delta`` / ``block_end`` cover every text block; the turn
    closes with ``turn_completed`` (success) or ``error`` (cap breach /
    Anthropic failure)."""

    async def test_happy_path_emits_full_envelope(self, repo_mocks):
        client = _make_client(_make_response(text="hello world"))

        result, events = await _run(client, repo_mocks)

        # Frame ordering: turn_started → block_start → text_delta → block_end → turn_completed
        types = [type(e) for e in events]
        assert types == [
            TurnStarted,
            BlockStart,
            TextDelta,
            BlockEnd,
            TurnCompleted,
        ]

        started = events[0]
        assert isinstance(started, TurnStarted)
        # ``turn_id`` on the wire matches the agent_turn UUID — the
        # endpoint relies on this so iOS can join the SSE stream back to
        # the durable row.
        assert started.turn_id == repo_mocks["_ids"]["turn_id"]

        block_start = events[1]
        assert isinstance(block_start, BlockStart)
        assert block_start.block["type"] == "text"
        assert block_start.block["text"] == ""
        block_id = block_start.block["block_id"]

        delta = events[2]
        assert isinstance(delta, TextDelta)
        assert delta.block_id == block_id
        assert delta.text == "hello world"

        end = events[3]
        assert isinstance(end, BlockEnd)
        assert end.block_id == block_id

        completed = events[4]
        assert isinstance(completed, TurnCompleted)
        assert completed.turn_id == repo_mocks["_ids"]["turn_id"]
        assert completed.terminal_state == "end_turn"
        assert completed.iterations_count == 1
        assert completed.total_cost_usd_micros == result.total_cost_usd_micros

    async def test_streamed_block_id_matches_persisted_block_id(
        self, repo_mocks
    ):
        # The acceptance criterion in B2.4 is that ``messages.content_blocks``
        # is populated with the streamed block — same ID end-to-end.
        client = _make_client(_make_response(text="match me"))

        result, events = await _run(client, repo_mocks)

        block_start = next(e for e in events if isinstance(e, BlockStart))
        wire_block_id = block_start.block["block_id"]

        persisted_blocks = repo_mocks["append_assistant_message"].call_args.kwargs[
            "content_blocks"
        ]
        assert persisted_blocks == [
            {
                "type": "text",
                "block_id": wire_block_id,
                "text": "match me",
            }
        ]
        assert result.assistant_message_blocks == persisted_blocks

    async def test_thinking_blocks_do_not_emit_user_facing_events(
        self, repo_mocks
    ):
        # Thinking blocks ride on Anthropic's stream but stay server-side;
        # only the text block produces wire events.
        client = _make_client(
            _make_response(
                text="answer",
                extra_blocks=[
                    ThinkingBlock(
                        thinking="hidden plan",
                        signature="sig",
                        type="thinking",
                    ),
                ],
            )
        )

        _result, events = await _run(client, repo_mocks)

        block_starts = [e for e in events if isinstance(e, BlockStart)]
        block_ends = [e for e in events if isinstance(e, BlockEnd)]
        # Exactly one text block round-trips on the wire; the thinking
        # block doesn't.
        assert len(block_starts) == 1
        assert len(block_ends) == 1
        assert block_starts[0].block["type"] == "text"

    async def test_iteration_cap_breach_emits_error_event(self, repo_mocks):
        client = _make_client(_make_response())

        _result, events = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_iterations=0)
        )

        # turn_started fires before the cap check (the row is already open),
        # then the loop short-circuits straight to error.
        assert [type(e) for e in events] == [TurnStarted, Error]
        err = events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.TURN_ITERATION_LIMIT
        assert err.message == "terminal_state=iteration_limit"

    async def test_anthropic_error_emits_error_event(self, repo_mocks):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        exc = anthropic.RateLimitError(
            "rate limited", response=response, body=None
        )
        client = _make_client(exc)

        _result, events = await _run(client, repo_mocks)

        assert [type(e) for e in events] == [TurnStarted, Error]
        err = events[1]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.MODEL_RATE_LIMIT

    async def test_max_tokens_stop_reason_emits_error_event(self, repo_mocks):
        # Anthropic-side cap (different from our HardCaps): the model
        # itself stops at ``max_tokens``. Loop maps to OUTPUT_TOKEN_LIMIT
        # so iOS surfaces the same code as a wall-side breach.
        client = _make_client(_make_response(stop_reason="max_tokens"))

        _result, events = await _run(client, repo_mocks)

        terminals = [
            e for e in events if isinstance(e, (TurnCompleted, Error))
        ]
        assert len(terminals) == 1
        err = terminals[0]
        assert isinstance(err, Error)
        assert err.code == ErrorCode.OUTPUT_TOKEN_LIMIT

    async def test_text_deltas_arrive_in_emit_order(self, repo_mocks):
        # Build a response with two text chunks (simulated by hand-crafting
        # the stream rather than going through ``_events_for``) and verify
        # the loop forwards them in arrival order to the emitter.
        final = _make_response(text="ab")
        events: list[Any] = [
            RawContentBlockStartEvent(
                content_block=TextBlock(text="", type="text"),
                index=0,
                type="content_block_start",
            ),
            RawContentBlockDeltaEvent(
                delta=AnthropicTextDelta(text="a", type="text_delta"),
                index=0,
                type="content_block_delta",
            ),
            RawContentBlockDeltaEvent(
                delta=AnthropicTextDelta(text="b", type="text_delta"),
                index=0,
                type="content_block_delta",
            ),
            RawContentBlockStopEvent(index=0, type="content_block_stop"),
        ]

        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(_FakeStream(events, final))
        )

        _result, wire_events = await _run(client, repo_mocks)

        deltas = [e for e in wire_events if isinstance(e, TextDelta)]
        assert [d.text for d in deltas] == ["a", "b"]
        # All deltas reference the block_id minted in the first ``block_start``.
        block_start = next(e for e in wire_events if isinstance(e, BlockStart))
        assert all(d.block_id == block_start.block["block_id"] for d in deltas)


# ---------- request shape ----------


class TestRequestShape:
    async def test_tools_kwarg_omitted_when_registry_empty(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        create_kwargs = client.messages.stream.call_args.kwargs
        assert "tools" not in create_kwargs
        assert create_kwargs["model"] == MODEL_ID
        assert create_kwargs["system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert create_kwargs["max_tokens"] == HardCaps().max_output_tokens

    async def test_thinking_config_sent_on_every_call(self, repo_mocks):
        # A1.7 requires every Anthropic call to enable extended thinking
        # with budget_tokens >= 1024 — Anthropic returns 400s otherwise
        # when thinking blocks roundtrip on later iterations.
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        create_kwargs = client.messages.stream.call_args.kwargs
        assert create_kwargs["thinking"] == {
            "type": "enabled",
            "budget_tokens": 1024,
        }

    async def test_tools_kwarg_included_when_registry_has_tools(
        self, repo_mocks
    ):
        # Sanity check the contract for Project C: when a non-empty registry
        # is passed, the loop forwards its spec (with the A1.8 cache marker
        # appended to the last entry). The actual Tool ABC and registry
        # implementation land later.
        spec = [
            {"name": "get_stock_info", "description": "...", "input_schema": {}},
            {"name": "get_quote", "description": "...", "input_schema": {}},
        ]

        class _Reg:
            @property
            def is_empty(self) -> bool:
                return False

            def to_anthropic_spec(self) -> list[dict[str, Any]]:
                return spec

        client = _make_client(_make_response())

        await _run(client, repo_mocks, tool_registry=_Reg())

        create_kwargs = client.messages.stream.call_args.kwargs
        # Only the last tool gets cache_control; earlier tools are unchanged.
        assert create_kwargs["tools"] == [
            {"name": "get_stock_info", "description": "...", "input_schema": {}},
            {
                "name": "get_quote",
                "description": "...",
                "input_schema": {},
                "cache_control": {"type": "ephemeral"},
            },
        ]
        # Registry's own list must not be mutated — the loop copies before
        # appending the cache marker.
        assert "cache_control" not in spec[-1]

    async def test_system_block_carries_cache_control(self, repo_mocks):
        # A1.8 acceptance: the system block sent to Anthropic must carry the
        # ephemeral cache marker so the prompt is cached across turns.
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        create_kwargs = client.messages.stream.call_args.kwargs
        assert create_kwargs["system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]


# ---------- cap breaches ----------


class TestCapBreaches:
    async def test_iteration_cap_breach_skips_anthropic_call(self, repo_mocks):
        client = _make_client(_make_response())

        result, _events = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_iterations=0)
        )

        assert result.terminal_state == "iteration_limit"
        assert result.iterations_count == 0
        assert result.assistant_message_blocks == []
        client.messages.stream.assert_not_called()
        # No model_invocation rows; assistant message not persisted.
        repo_mocks["record_model_invocation"].assert_not_awaited()
        repo_mocks["append_assistant_message"].assert_not_awaited()
        # But the agent_turn IS completed with the breach state + error code.
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "iteration_limit"
        assert kwargs["error_code"] == ErrorCode.TURN_ITERATION_LIMIT.value

    async def test_wall_clock_cap_breach(self, repo_mocks, monkeypatch):
        # Shift the monotonic clock far enough forward that the very first
        # ``check_caps`` reports TIMEOUT. ``time.monotonic`` is called once
        # to seed ``LoopState.started_at_monotonic`` and again inside
        # ``check_caps`` — make the second call return a value > the first
        # by more than max_wall_clock_s.
        real_monotonic = time.monotonic
        offset = {"value": 0.0}

        def fake_monotonic() -> float:
            offset["value"] += 1000.0
            return real_monotonic() + offset["value"]

        monkeypatch.setattr("app.ai.runtime.loop.time.monotonic", fake_monotonic)
        client = _make_client(_make_response())

        result, _events = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_wall_clock_s=10.0)
        )

        assert result.terminal_state == "timeout"
        client.messages.stream.assert_not_called()

    async def test_output_token_cap_breach_after_first_iteration(
        self, repo_mocks
    ):
        # First iteration succeeds and reports 1500 output tokens; the
        # ``pause_turn`` stop reason continues the loop. The second
        # iteration's ``check_caps`` then breaches because
        # state.output_tokens (1500) >= max_output_tokens (1100), so the
        # loop exits with the cap-breach terminal state.
        # ``max_output_tokens`` must stay > 1024 (thinking budget) for
        # ``run_agent_turn`` to accept the caps.
        client = _make_client(
            _make_response(
                stop_reason="pause_turn",
                output_tokens=1500,
            )
        )

        result, _events = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_output_tokens=1100)
        )

        assert result.terminal_state == "output_token_limit"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.OUTPUT_TOKEN_LIMIT.value
        # Only one Anthropic call: iteration 2's cap check fires before
        # the second stream() would have been issued.
        client.messages.stream.assert_called_once()

    async def test_max_output_tokens_at_or_below_thinking_budget_raises(
        self, repo_mocks
    ):
        # Anthropic 400s when budget_tokens >= max_tokens. The loop fails
        # fast at the entry to surface the misconfig before any DB writes.
        client = _make_client(_make_response())

        with pytest.raises(ValueError, match="thinking budget"):
            await _run(
                client, repo_mocks, hard_caps=HardCaps(max_output_tokens=1024)
            )

        # No persistence side-effects from the rejected call.
        repo_mocks["append_user_message"].assert_not_awaited()
        repo_mocks["start_agent_turn"].assert_not_awaited()
        client.messages.stream.assert_not_called()


# ---------- A1.7: extended thinking + signature roundtripping ----------


class TestThinkingRoundtrip:
    async def test_pause_turn_continues_loop_to_next_iteration(self, repo_mocks):
        # ``pause_turn`` is Anthropic's "continue verbatim" signal. The loop
        # must continue past it — a single ``pause_turn`` followed by
        # ``end_turn`` should yield two iterations.
        client = _make_client(
            [
                _make_response(text="working...", stop_reason="pause_turn"),
                _make_response(text="done", stop_reason="end_turn"),
            ]
        )

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2
        assert client.messages.stream.call_count == 2

    async def test_iteration_two_request_includes_iteration_one_thinking(
        self, repo_mocks
    ):
        # The R1 contract: model_invocations.response_content from
        # iteration N is what gets passed back as iteration N+1's assistant
        # message — never reconstructed. Verify the thinking block (with
        # signature) survives the roundtrip byte-for-byte.
        #
        # The loop reuses (and mutates) one ``messages`` list across
        # iterations, so MagicMock's call-args recording — which holds the
        # list by reference — would show the post-mutation state and miss
        # what was actually sent. Snapshot in a side_effect instead.
        import copy

        thinking = ThinkingBlock(
            thinking="careful reasoning",
            signature="sig_iter_1",
            type="thinking",
        )
        responses = [
            _make_response(
                text="working",
                stop_reason="pause_turn",
                extra_blocks=[thinking],
            ),
            _make_response(text="final", stop_reason="end_turn"),
        ]
        captured_messages: list[list[dict[str, Any]]] = []

        def _stream_side_effect(**kwargs: Any) -> _FakeStreamManager:
            captured_messages.append(copy.deepcopy(kwargs["messages"]))
            response = responses[len(captured_messages) - 1]
            return _FakeStreamManager(_FakeStream(_events_for(response), response))

        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(side_effect=_stream_side_effect)

        await _run(client, repo_mocks)

        assert len(captured_messages) == 2
        # Iteration 2's request must contain exactly one assistant turn —
        # iteration 1's response, with the signed thinking block intact.
        sent_messages = captured_messages[1]
        assistant_turns = [m for m in sent_messages if m["role"] == "assistant"]
        assert len(assistant_turns) == 1
        roundtripped = assistant_turns[0]["content"]
        thinking_blocks = [b for b in roundtripped if b.get("type") == "thinking"]
        assert len(thinking_blocks) == 1
        assert thinking_blocks[0]["thinking"] == "careful reasoning"
        assert thinking_blocks[0]["signature"] == "sig_iter_1"

    async def test_total_thinking_tokens_sums_per_iteration_estimates(
        self, repo_mocks
    ):
        # The heuristic estimates ``len(thinking_text) // 4`` per iteration
        # and accumulates into ``agent_turns.total_thinking_tokens``.
        # 16 chars and 24 chars → 4 + 6 = 10 tokens.
        client = _make_client(
            [
                _make_response(
                    text="...",
                    stop_reason="pause_turn",
                    extra_blocks=[
                        ThinkingBlock(
                            thinking="x" * 16,
                            signature="sig_a",
                            type="thinking",
                        ),
                    ],
                ),
                _make_response(
                    text="done",
                    stop_reason="end_turn",
                    extra_blocks=[
                        ThinkingBlock(
                            thinking="y" * 24,
                            signature="sig_b",
                            type="thinking",
                        ),
                    ],
                ),
            ]
        )

        await _run(client, repo_mocks)

        complete_kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert complete_kwargs["total_thinking_tokens"] == 10
        # Each iteration's record_model_invocation also carries its own
        # per-iteration estimate.
        per_iter = [
            call.kwargs["thinking_tokens"]
            for call in repo_mocks["record_model_invocation"].await_args_list
        ]
        assert per_iter == [4, 6]


# ---------- exception handling ----------


class TestExceptions:
    async def test_anthropic_rate_limit_returns_error_state(self, repo_mocks):
        # ``RateLimitError`` requires a ``response`` arg; build a minimal one
        # so the SDK exception constructs cleanly.
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        exc = anthropic.RateLimitError("rate limited", response=response, body=None)
        client = _make_client(exc)

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "error"
        assert result.iterations_count == 0
        # Function returns rather than raising.
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "error"
        assert kwargs["error_code"] == ErrorCode.MODEL_RATE_LIMIT.value
        # No model_invocation persisted because the call failed before we
        # had a response to record.
        repo_mocks["record_model_invocation"].assert_not_awaited()

    async def test_max_tokens_stop_reason_maps_to_output_token_limit(
        self, repo_mocks
    ):
        client = _make_client(_make_response(stop_reason="max_tokens"))

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "output_token_limit"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.OUTPUT_TOKEN_LIMIT.value

    async def test_unexpected_tool_use_in_v0_marks_internal_error(
        self, repo_mocks
    ):
        # No tools are registered, but Anthropic returned tool_use anyway —
        # treat as misconfiguration.
        client = _make_client(_make_response(stop_reason="tool_use"))

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "error"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.INTERNAL_ERROR.value


# ---------- langfuse instrumentation ----------


class _RecordingLangfuse:
    """Records every call to ``start_as_current_observation`` and the
    ``update`` calls made on the yielded observation.

    Mirrors the surface ``run_agent_turn`` consumes so we can assert on the
    trace_id, observation types, and update payloads without standing up a
    real Langfuse backend.
    """

    def __init__(self) -> None:
        self.observations: list[dict[str, Any]] = []

    def start_as_current_observation(self, **kwargs: Any):
        from contextlib import contextmanager

        record: dict[str, Any] = {"kwargs": kwargs, "updates": []}
        self.observations.append(record)

        # ``span`` mirrors LangfuseSpan / LangfuseGeneration: ``.update(...)``
        # captures kwargs into the record and returns ``span`` for chaining.
        span = MagicMock()
        span.update.side_effect = (
            lambda **u: record["updates"].append(u) or span
        )

        @contextmanager
        def cm():
            yield span

        return cm()


class TestLangfuseInstrumentation:
    """A3.2 acceptance: a trace per turn with the expected tags, plus a
    ``generation`` observation per Anthropic call cross-referenced by
    ``agent_turn.id`` (used as the trace_id)."""

    async def test_outer_observation_uses_turn_id_hex_as_trace_id(
        self, repo_mocks
    ):
        client = _make_client(_make_response())
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        # First observation is the outer "agent" span.
        outer = recorder.observations[0]["kwargs"]
        assert outer["as_type"] == "agent"
        assert outer["name"] == "agent_turn"

        expected_trace_id = repo_mocks["_ids"]["turn_id"].hex
        assert outer["trace_context"] == {"trace_id": expected_trace_id}
        assert outer["input"] == {"user_message": "hello"}

    async def test_generation_observation_per_anthropic_call(self, repo_mocks):
        client = _make_client(_make_response(text="answer"))
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        # Second observation is the per-iteration generation.
        gen = recorder.observations[1]["kwargs"]
        assert gen["as_type"] == "generation"
        assert gen["name"] == "anthropic.messages.create"
        assert gen["model"] == MODEL_ID
        # A1.8 marks the system block with cache_control; the input is
        # captured verbatim including that marker.
        assert gen["input"] == {
            "system": [
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT.text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [],
        }
        assert gen["metadata"] == {"iteration_index": 0}

    async def test_generation_update_carries_response_content(self, repo_mocks):
        client = _make_client(_make_response(text="answer"))
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        gen_record = recorder.observations[1]
        assert len(gen_record["updates"]) == 1
        update = gen_record["updates"][0]
        assert update["output"] == [
            {"citations": None, "text": "answer", "type": "text"}
        ]

    async def test_generation_update_attaches_usage_and_cost(
        self, repo_mocks
    ):
        # A3.3 acceptance: the Langfuse trace must show USD cost per turn and
        # a usage breakdown. ``cost_details.total`` mirrors
        # ``cost_usd_micros`` (in USD), and ``usage_details`` carries the
        # per-bucket token split with an explicit ``total`` so thinking — which
        # Anthropic already folds into ``output_tokens`` — doesn't double-count.
        response = _make_response(
            text="answer",
            input_tokens=42,
            output_tokens=11,
            extra_blocks=[
                ThinkingBlock(
                    thinking="x" * 32,  # 32 chars / 4 = 8 thinking tokens
                    signature="sig_a",
                    type="thinking",
                ),
            ],
        )
        client = _make_client(response)
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        update = recorder.observations[1]["updates"][0]
        assert update["usage_details"] == {
            "input": 42,
            "output": 11,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "thinking": 8,
            # ``total`` is ``input + output + cache_read + cache_creation``;
            # ``thinking`` is omitted because it is already inside
            # ``output_tokens``, so including it would double-count.
            "total": 53,
        }
        expected_cost_usd = (
            cost_usd_micros(response.usage, MODEL_ID) / 1_000_000
        )
        assert update["cost_details"] == {"total": expected_cost_usd}

    async def test_outer_observation_update_carries_terminal_state(
        self, repo_mocks
    ):
        client = _make_client(_make_response(text="hi"))
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        outer_updates = recorder.observations[0]["updates"]
        assert len(outer_updates) == 1
        update = outer_updates[0]
        assert update["output"]["terminal_state"] == "end_turn"
        assert update["output"]["iterations"] == 1
        assert update["level"] == "DEFAULT"
        assert update["status_message"] is None

    async def test_anthropic_error_marks_outer_and_inner_spans_as_error(
        self, repo_mocks
    ):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(429, request=request)
        exc = anthropic.RateLimitError(
            "rate limited", response=response, body=None
        )
        client = _make_client(exc)
        recorder = _RecordingLangfuse()

        await _run(client, repo_mocks, langfuse=recorder)

        # The generation span captured the failure (no `output` update).
        gen_updates = recorder.observations[1]["updates"]
        assert len(gen_updates) == 1
        assert gen_updates[0]["level"] == "ERROR"
        assert "RateLimitError" in gen_updates[0]["status_message"]

        # The outer agent span ends with ERROR level + error code in
        # status_message so the trace is filterable in Langfuse.
        outer_updates = recorder.observations[0]["updates"]
        assert outer_updates[0]["level"] == "ERROR"
        assert outer_updates[0]["status_message"] == (
            ErrorCode.MODEL_RATE_LIMIT.value
        )

    async def test_cap_breach_does_not_open_generation_observation(
        self, repo_mocks
    ):
        # Iteration cap of 0 means the loop never makes an Anthropic call.
        # Only the outer "agent" observation should be opened — no generation.
        client = _make_client(_make_response())
        recorder = _RecordingLangfuse()

        await _run(
            client,
            repo_mocks,
            langfuse=recorder,
            hard_caps=HardCaps(max_iterations=0),
        )

        as_types = [o["kwargs"]["as_type"] for o in recorder.observations]
        assert as_types == ["agent"]
        outer_updates = recorder.observations[0]["updates"]
        assert outer_updates[0]["level"] == "ERROR"
        assert outer_updates[0]["status_message"] == (
            ErrorCode.TURN_ITERATION_LIMIT.value
        )
