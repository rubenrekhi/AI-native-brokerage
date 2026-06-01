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
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
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
    ToolUseBlock,
    Usage,
)

from app.ai.observability.langfuse import _NoopLangfuse
from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.cost import cost_usd_micros
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import (
    EMPTY_REGISTRY,
    ModelConfig,
    ServerToolsConfig,
    ToolRegistry,
)
from app.ai.tools import ToolHttpClients
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import (
    BlockData,
    BlockEnd,
    BlockStart,
    Error,
    Event,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)
from app.schemas.conversations import AttachedContextRequest, ContextKind

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

    Text and thinking blocks emit a real delta event in addition to the
    start/stop bracket — the loop branches on both ``text_delta`` and
    ``thinking_delta`` to forward visible content to iOS. Other block
    shapes are passed through with start/stop only.
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

    invocation_id = uuid.uuid4()
    invocation_row = type("Inv", (), {"id": invocation_id})()

    mocks = {
        "append_user_message": AsyncMock(return_value=user_msg),
        "load_history": AsyncMock(return_value=[]),
        "start_agent_turn": AsyncMock(return_value=turn),
        "record_model_invocation": AsyncMock(return_value=invocation_row),
        "record_tool_execution": AsyncMock(),
        "append_assistant_message": AsyncMock(return_value=assistant_msg),
        "complete_agent_turn": AsyncMock(),
        "_ids": {
            "user_msg_id": user_msg_id,
            "turn_id": turn_id,
            "assistant_msg_id": assistant_msg_id,
            "invocation_id": invocation_id,
        },
    }
    for name in (
        "append_user_message",
        "load_history",
        "start_agent_turn",
        "record_model_invocation",
        "record_tool_execution",
        "append_assistant_message",
        "complete_agent_turn",
    ):
        monkeypatch.setattr(
            "app.ai.runtime.loop.ConversationRepository." + name, mocks[name]
        )
    # The supersede sweep runs in initialize_turn against the stub session;
    # patch it so unit tests don't need a real DB.
    supersede = AsyncMock(return_value=0)
    mocks["supersede_pending_for_conversation"] = supersede
    monkeypatch.setattr(
        "app.ai.runtime.flow.turn_lifecycle."
        "PendingActionRepository.supersede_pending_for_conversation",
        supersede,
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
    user_context: AttachedContextRequest | None = None,
    langfuse: Any = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    emitter: SSEEmitter | None = None,
    server_tools_config: ServerToolsConfig | None = None,
    time_context: str | None = None,
    user_profile: str | None = None,
    persist_user_message: bool | None = None,
) -> tuple[Any, list[Event]]:
    """Run the loop and return ``(result, events)``.

    Drives the emitter's iterator concurrently so a fast-emitting loop
    can't fill the queue and deadlock on ``emit``. ``emitter`` defaults
    to a fresh :class:`SSEEmitter`.
    """
    em = emitter or SSEEmitter()
    drain_task = asyncio.create_task(_drain(em))

    kwargs: dict[str, Any] = {
        "user_id": user_id or uuid.uuid4(),
        "conversation_id": conversation_id or uuid.uuid4(),
        "user_message": user_message,
        "anthropic_client": client,
        "db_factory": _make_db_factory(),
        "tool_registry": tool_registry or EMPTY_REGISTRY,
        "http_clients": ToolHttpClients(),
        "system_prompt": SYSTEM_PROMPT,
        "model_config": ModelConfig(model_id=MODEL_ID),
        "hard_caps": hard_caps or HardCaps(),
        "langfuse": langfuse if langfuse is not None else _NoopLangfuse(),
        "environment": "test",
        "sse_emitter": em,
    }
    if server_tools_config is not None:
        kwargs["server_tools_config"] = server_tools_config
    if user_context is not None:
        kwargs["user_context"] = user_context
    if time_context is not None:
        kwargs["time_context"] = time_context
    if user_profile is not None:
        kwargs["user_profile"] = user_profile
    if persist_user_message is not None:
        kwargs["persist_user_message"] = persist_user_message

    try:
        result = await run_agent_turn(**kwargs)
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
        # The loop mints a server-assigned ULID ``block_id`` so the persisted
        # shape matches assistant text blocks — iOS resume rejects blocks
        # without it. Verify the user-visible fields without pinning the ULID.
        assert len(kwargs["content_blocks"]) == 1
        block = kwargs["content_blocks"][0]
        assert block["type"] == "text"
        assert block["text"] == "how is AMD"
        assert isinstance(block["block_id"], str) and block["block_id"]

    async def test_starts_agent_turn_with_prompt_hash_and_model(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        kwargs = repo_mocks["start_agent_turn"].call_args.kwargs
        assert kwargs["prompt_hash"] == SYSTEM_PROMPT.hash
        assert kwargs["model_id"] == MODEL_ID
        assert kwargs["user_message_id"] == repo_mocks["_ids"]["user_msg_id"]

    async def test_system_initiated_turn_skips_user_bubble_and_supersede(
        self, repo_mocks
    ):
        # A HIL confirm seeds a turn without persisting a user bubble or
        # superseding sibling proposals; the agent_turn has no user_message_id.
        client = _make_client(_make_response())

        await _run(
            client,
            repo_mocks,
            user_message="[the user confirmed the deposit; result: success]",
            persist_user_message=False,
        )

        repo_mocks["append_user_message"].assert_not_awaited()
        repo_mocks["supersede_pending_for_conversation"].assert_not_awaited()
        repo_mocks["start_agent_turn"].assert_awaited_once()
        assert (
            repo_mocks["start_agent_turn"].call_args.kwargs["user_message_id"]
            is None
        )

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

    async def test_digest_context_injects_card_content_hint_not_system_prompt(
        self, repo_mocks
    ):
        # SEV-615 B: a digest card rides the unified ``context`` channel
        # (``kind=digest``). Its content reaches the model via the
        # ``DigestContextBlock`` hint on the *current turn* — not the system
        # prompt — and ``card_context_source`` is still derived for the chip.
        digest_card = {
            "id": "digest-1",
            "kind": "big_move",
            "related_symbols": ["AMD"],
            "card_context": {"headline": "AMD moved 5%"},
        }
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "t", "text": "what changed?"},
                {
                    "type": "context",
                    "block_id": "c",
                    "kind": "digest",
                    "data": digest_card,
                },
            )
        ]
        client = _make_client(_make_response(text="answer"))
        captured = _capture_messages(client)

        _, events = await _run(
            client,
            repo_mocks,
            user_message="what changed?",
            user_context=AttachedContextRequest(
                kind=ContextKind.DIGEST, data=digest_card
            ),
        )

        # System prompt is untouched — no digest injection there.
        kwargs = repo_mocks["record_model_invocation"].call_args.kwargs
        assert kwargs["request_system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # The card content rides the current turn's user message instead.
        hint = captured["messages"][-1]["content"][-1]
        assert hint["type"] == "text"
        assert hint["text"].startswith(
            "The user opened the chat from a Daily Digest card."
        )
        assert "big_move" in hint["text"]
        assert "AMD moved 5%" in hint["text"]

        # The source chip still resolves from the digest context.
        started = events[0]
        assert isinstance(started, TurnStarted)
        assert started.card_context_source == {
            "symbol": "AMD",
            "kind": "big_move",
        }

    async def test_time_context_rides_current_user_message_not_system(
        self, repo_mocks
    ):
        # The live clock must sit *after* every cache breakpoint so it never
        # invalidates the cached prefix: it rides the current user message as
        # the last block, and the system prompt stays a single cached block.
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "u", "text": "hello"}
            )
        ]
        client = _make_client(_make_response())
        captured = _capture_messages(client)

        await _run(client, repo_mocks, time_context="It is 3:45 PM EDT.")

        kwargs = repo_mocks["record_model_invocation"].call_args.kwargs
        assert kwargs["request_system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert captured["messages"][-1]["content"][-1] == {
            "type": "text",
            "text": "It is 3:45 PM EDT.",
        }

    async def test_no_time_context_keeps_single_cached_system_block(
        self, repo_mocks
    ):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        kwargs = repo_mocks["record_model_invocation"].call_args.kwargs
        assert len(kwargs["request_system"]) == 1

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

    async def test_thinking_blocks_emit_thinking_wire_envelope(
        self, repo_mocks
    ):
        # SEV-571: thinking blocks now ship to iOS as a ``ThinkingBlock``
        # envelope. The wire shape is ``block_start`` (state=streaming) →
        # one ``text_delta`` per ``thinking_delta`` → ``block_data``
        # patch flipping state to ``complete`` → ``block_end``. The
        # signed Anthropic block still rides on
        # ``model_invocations.response_content`` for A1.7's signature
        # roundtripping — that is asserted by the integration test in
        # ``test_thinking_roundtrip.py``.
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
        # One thinking + one text envelope on the wire.
        assert len(block_starts) == 2
        assert len(block_ends) == 2

        thinking_start = next(
            e for e in block_starts if e.block["type"] == "thinking"
        )
        assert thinking_start.block["state"] == "streaming"
        assert thinking_start.block["redacted"] is False
        assert isinstance(thinking_start.block["block_id"], str)
        thinking_id = thinking_start.block["block_id"]

        # Exactly one text_delta for the thinking block, carrying the
        # thinking text. The text block also emits its own delta, but
        # _events_for puts the thinking block at index 1 so the test
        # asserts by block_id rather than position.
        thinking_deltas = [
            e
            for e in events
            if isinstance(e, TextDelta) and e.block_id == thinking_id
        ]
        assert len(thinking_deltas) == 1
        assert thinking_deltas[0].text == "hidden plan"

        # The state→complete patch lands as a ``BlockData`` event
        # targeting the thinking block.
        from app.ai.transport.events import BlockData

        thinking_patches = [
            e
            for e in events
            if isinstance(e, BlockData) and e.block_id == thinking_id
        ]
        assert thinking_patches == [
            BlockData(
                id=thinking_patches[0].id,
                block_id=thinking_id,
                data={"state": "complete"},
            )
        ]
        # And the bracket closes.
        thinking_ends = [
            e for e in block_ends if e.block_id == thinking_id
        ]
        assert len(thinking_ends) == 1

        # The state→complete patch MUST land before the close bracket;
        # an iOS client that received them out of order could drop the
        # patch as targeting a closed block.
        assert events.index(thinking_patches[0]) < events.index(thinking_ends[0])

    async def test_redacted_thinking_block_emits_complete_envelope(
        self, repo_mocks
    ):
        # SEV-571: ``redacted_thinking`` blocks have encrypted content
        # we can't show. Emit a single ``block_start`` with
        # ``redacted=true, state=complete`` followed immediately by
        # ``block_end`` — no deltas, no state patch.
        from anthropic.types import RedactedThinkingBlock

        client = _make_client(
            _make_response(
                text="answer",
                extra_blocks=[
                    RedactedThinkingBlock(
                        data="encrypted_bytes_blob",
                        type="redacted_thinking",
                    ),
                ],
            )
        )

        _result, events = await _run(client, repo_mocks)

        block_starts = [e for e in events if isinstance(e, BlockStart)]
        thinking_starts = [
            e for e in block_starts if e.block["type"] == "thinking"
        ]
        assert len(thinking_starts) == 1
        redacted = thinking_starts[0]
        assert redacted.block["redacted"] is True
        assert redacted.block["state"] == "complete"
        assert redacted.block["text"] == ""

        redacted_id = redacted.block["block_id"]
        # No deltas for the redacted block.
        redacted_deltas = [
            e
            for e in events
            if isinstance(e, TextDelta) and e.block_id == redacted_id
        ]
        assert redacted_deltas == []
        # Bracket closes.
        block_ends = [e for e in events if isinstance(e, BlockEnd)]
        assert any(e.block_id == redacted_id for e in block_ends)

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
        # Tools carry no cache marker — they sit before ``system`` in the cache
        # prefix, so the system-prompt breakpoint already caches them.
        assert create_kwargs["tools"] == [
            {"name": "get_stock_info", "description": "...", "input_schema": {}},
            {"name": "get_quote", "description": "...", "input_schema": {}},
        ]
        assert all("cache_control" not in t for t in create_kwargs["tools"])

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

    async def test_user_profile_added_as_second_cached_system_block(
        self, repo_mocks
    ):
        # A stable per-user profile rides a second system block with its own
        # cache breakpoint — after the static prompt, before messages.
        client = _make_client(_make_response())

        await _run(
            client, repo_mocks, user_profile="## About the user\n\nJane."
        )

        create_kwargs = client.messages.stream.call_args.kwargs
        assert create_kwargs["system"] == [
            {
                "type": "text",
                "text": SYSTEM_PROMPT.text,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": "## About the user\n\nJane.",
                "cache_control": {"type": "ephemeral"},
            },
        ]

    async def test_no_user_profile_keeps_single_system_block(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        create_kwargs = client.messages.stream.call_args.kwargs
        assert len(create_kwargs["system"]) == 1

    async def test_history_drops_non_text_ui_blocks(self, repo_mocks, monkeypatch):
        # SEV-571: ``ThinkingBlock`` (and the existing ``StatusBlock`` /
        # ``StockCardBlock`` UI-only variants) must not survive into the
        # next turn's Anthropic request — Anthropic 400s on unknown
        # ``type`` values. ``_to_anthropic_content`` should keep only
        # ``text`` blocks.
        import copy

        prior_user = type(
            "M",
            (),
            {
                "role": "user",
                "content_blocks": [{"type": "text", "text": "first turn"}],
            },
        )()
        prior_assistant = type(
            "M",
            (),
            {
                "role": "assistant",
                "content_blocks": [
                    {
                        "type": "thinking",
                        "block_id": "blk_th",
                        "text": "Let me think.",
                        "redacted": False,
                        "state": "complete",
                    },
                    {
                        "type": "status",
                        "block_id": "blk_status",
                        "label": "Fetched price",
                        "state": "complete",
                    },
                    {
                        "type": "text",
                        "block_id": "blk_text",
                        "text": "first answer",
                    },
                ],
            },
        )()
        new_user = type(
            "M",
            (),
            {
                "role": "user",
                "content_blocks": [{"type": "text", "text": "follow-up"}],
            },
        )()
        repo_mocks["load_history"] = AsyncMock(
            return_value=[prior_user, prior_assistant, new_user]
        )
        import app.ai.runtime.loop as loop_module

        monkeypatch.setattr(
            loop_module.ConversationRepository,
            "load_history",
            repo_mocks["load_history"],
        )

        captured: list[list[dict[str, Any]]] = []
        final = _make_response(text="second answer")

        def _stream_side_effect(**kwargs: Any) -> _FakeStreamManager:
            captured.append(copy.deepcopy(kwargs["messages"]))
            return _FakeStreamManager(_FakeStream(_events_for(final), final))

        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(side_effect=_stream_side_effect)

        await _run(client, repo_mocks, user_message="follow-up")

        assert len(captured) == 1
        sent_messages = captured[0]
        # The thinking + status blocks are dropped; only the text block
        # survives — without its ``block_id`` (which Anthropic's content-block
        # schema rejects), and carrying the history cache breakpoint since it
        # is the last prior-turn message.
        assert sent_messages[1]["content"] == [
            {
                "type": "text",
                "text": "first answer",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def test_history_assistant_text_blocks_strip_block_id(
        self, repo_mocks
    ):
        # Regression: B2.4 persists assistant text blocks with a server-
        # assigned ``block_id`` so iOS can correlate the row with the SSE
        # wire. Anthropic's content-block schema doesn't accept that
        # field, and a follow-up turn that loaded history verbatim was
        # 400ing inside ``messages.stream()`` and surfacing as a generic
        # ``INTERNAL_ERROR`` SSE frame. The transform must strip
        # ``block_id`` before re-sending.
        import copy

        prior_user = type(
            "M",
            (),
            {
                "role": "user",
                "content_blocks": [{"type": "text", "text": "first turn"}],
            },
        )()
        prior_assistant = type(
            "M",
            (),
            {
                "role": "assistant",
                "content_blocks": [
                    {
                        "type": "text",
                        "block_id": "01KR2HBHWVQS5B5TK8QEPSQRKZ",
                        "text": "first answer",
                    }
                ],
            },
        )()
        new_user = type(
            "M",
            (),
            {
                "role": "user",
                "content_blocks": [{"type": "text", "text": "follow-up"}],
            },
        )()
        repo_mocks["load_history"] = AsyncMock(
            return_value=[prior_user, prior_assistant, new_user]
        )
        import app.ai.runtime.loop as loop_module

        loop_module.ConversationRepository.load_history = repo_mocks[
            "load_history"
        ]

        # The loop reuses (and mutates) the ``messages`` list across
        # iterations — capturing kwargs would show the post-mutation
        # shape. Snapshot at call time via a side_effect instead.
        captured: list[list[dict[str, Any]]] = []
        final = _make_response(text="second answer")

        def _stream_side_effect(**kwargs: Any) -> _FakeStreamManager:
            captured.append(copy.deepcopy(kwargs["messages"]))
            return _FakeStreamManager(_FakeStream(_events_for(final), final))

        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(side_effect=_stream_side_effect)

        await _run(client, repo_mocks, user_message="follow-up")

        assert len(captured) == 1
        sent_messages = captured[0]
        assert [m["role"] for m in sent_messages] == [
            "user",
            "assistant",
            "user",
        ]
        # Anthropic-shape only — no ``block_id``. Carries the history cache
        # breakpoint: it is the last prior-turn message.
        assert sent_messages[1]["content"] == [
            {
                "type": "text",
                "text": "first answer",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        # User blocks pass through unchanged — they never carry a block_id,
        # and this one is before the breakpoint so it stays unmarked.
        assert sent_messages[0]["content"] == [
            {"type": "text", "text": "first turn"}
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

    async def test_tool_use_with_no_registered_tool_marks_internal_error(
        self, repo_mocks
    ):
        # Empty registry advertises no tools, but Anthropic emitted a
        # tool_use block anyway — i.e. a misconfiguration. C1.2 funnels
        # the resulting ``KeyError`` from ``ToolRegistry.get`` into
        # ``INTERNAL_ERROR`` rather than ``TOOL_ERROR`` (the latter is
        # reserved for tools that fail during ``execute``).
        response = Message(
            id="msg_unknown_tool",
            content=[
                ToolUseBlock(
                    id="toolu_unknown",
                    name="not_registered",
                    input={"x": 1},
                    type="tool_use",
                )
            ],
            model=MODEL_ID,
            role="assistant",
            stop_reason="tool_use",
            type="message",
            usage=Usage(input_tokens=10, output_tokens=4),
        )
        client = _make_client(response)

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


# ---------- B3.3: cancellation ----------


class TestCancellation:
    """B3.3: ``disconnect_check`` propagates client disconnect into the loop
    as :class:`asyncio.CancelledError`. The ``except`` clause sets
    ``terminal_state='cancelled'`` and ``error_code=CANCELLED``, the
    ``finally`` block persists those onto the agent_turn row, and the
    CancelledError re-propagates to the caller. No terminal SSE frame is
    emitted because the connection that would consume it is gone.
    """

    @staticmethod
    async def _run_until_cancelled(
        client: Any,
        repo_mocks: dict[str, Any],
        *,
        disconnect_check: Callable[[], Awaitable[bool]],
        hard_caps: HardCaps | None = None,
        emitter: SSEEmitter | None = None,
    ) -> list[Event]:
        """Drive the loop expecting a CancelledError; return drained events.

        Mirrors the ``_run`` helper but expects cancellation. The drain task
        is awaited on the cleanup path so pytest doesn't flag it as a leaked
        coroutine.
        """
        em = emitter or SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))
        try:
            with pytest.raises(asyncio.CancelledError):
                await run_agent_turn(
                    user_id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    user_message="hello",
                    anthropic_client=client,
                    db_factory=_make_db_factory(),
                    tool_registry=EMPTY_REGISTRY,
                    http_clients=ToolHttpClients(),
                    system_prompt=SYSTEM_PROMPT,
                    model_config=ModelConfig(model_id=MODEL_ID),
                    hard_caps=hard_caps or HardCaps(),
                    langfuse=_NoopLangfuse(),
                    environment="test",
                    sse_emitter=em,
                    disconnect_check=disconnect_check,
                )
        finally:
            await em.close()
        return await drain_task

    async def test_iteration_boundary_disconnect_raises_cancelled_error(
        self, repo_mocks
    ):
        # disconnect_check returns True on the first call (iteration-boundary
        # poll). The loop self-raises CancelledError before any Anthropic
        # call is made.
        client = _make_client(_make_response())
        check_calls = 0

        async def disconnect() -> bool:
            nonlocal check_calls
            check_calls += 1
            return True

        events = await self._run_until_cancelled(
            client, repo_mocks, disconnect_check=disconnect
        )

        # Polled exactly once at the iteration boundary, then raised — the
        # streaming poll path was never reached.
        assert check_calls == 1
        client.messages.stream.assert_not_called()

        # turn_started fires before the iteration begins (the row is
        # already open); no terminal frame follows because the client is
        # gone.
        assert [type(e) for e in events] == [TurnStarted]

        # Audit row reflects the cancellation. assistant_message_id is
        # None because no blocks were assembled.
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "cancelled"
        assert kwargs["error_code"] == ErrorCode.CANCELLED.value
        assert kwargs["assistant_message_id"] is None
        repo_mocks["append_assistant_message"].assert_not_awaited()
        # No Anthropic call → no model_invocation row.
        repo_mocks["record_model_invocation"].assert_not_awaited()

    async def test_mid_stream_disconnect_raises_cancelled_error(
        self, repo_mocks
    ):
        # disconnect_check returns False at the iteration boundary, then
        # True from the first mid-stream poll (after the Nth text delta).
        # The loop is mid-Anthropic-stream when it self-raises; the
        # streaming context's __aexit__ closes the upstream connection.
        N = 16  # _DISCONNECT_CHECK_DELTA_INTERVAL in app.ai.runtime.loop
        text_chunks = ["c"] * (N + 4)
        full_text = "".join(text_chunks)
        final = _make_response(text=full_text)
        events_list: list[Any] = [
            RawContentBlockStartEvent(
                content_block=TextBlock(text="", type="text"),
                index=0,
                type="content_block_start",
            ),
            *[
                RawContentBlockDeltaEvent(
                    delta=AnthropicTextDelta(text=c, type="text_delta"),
                    index=0,
                    type="content_block_delta",
                )
                for c in text_chunks
            ],
            RawContentBlockStopEvent(index=0, type="content_block_stop"),
        ]
        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(_FakeStream(events_list, final))
        )

        check_calls = 0

        async def disconnect() -> bool:
            nonlocal check_calls
            check_calls += 1
            # First call is the iteration-boundary poll; subsequent calls
            # are the mid-stream cadence.
            return check_calls > 1

        wire_events = await self._run_until_cancelled(
            client, repo_mocks, disconnect_check=disconnect
        )

        # The stream WAS opened (one Anthropic call). The mid-stream poll
        # fired only after the cadence interval; the loop emitted exactly
        # N text_deltas and then cancelled — the remaining 4 deltas the
        # fake stream would have produced never made it onto the wire.
        client.messages.stream.assert_called_once()
        text_deltas = [e for e in wire_events if isinstance(e, TextDelta)]
        assert len(text_deltas) == N

        # Open envelope only (turn_started + block_start + N deltas); no
        # block_end, no terminal frame.
        assert [type(e) for e in wire_events] == [
            TurnStarted,
            BlockStart,
            *([TextDelta] * N),
        ]

        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "cancelled"
        assert kwargs["error_code"] == ErrorCode.CANCELLED.value
        # B3.4: cancellation_reason populated so the audit trail
        # distinguishes a client disconnect from any other failure.
        assert kwargs["cancellation_reason"] is not None
        # B3.4: the N text deltas that reached the wire before the
        # cancellation are persisted as a partial assistant block — the
        # agent_turn row points at that message.
        assert kwargs["assistant_message_id"] is not None
        repo_mocks["append_assistant_message"].assert_awaited_once()
        persisted = repo_mocks["append_assistant_message"].call_args.kwargs[
            "content_blocks"
        ]
        assert len(persisted) == 1
        assert persisted[0]["type"] == "text"
        # Each delta in the fake stream is "c"; N of them concatenate to
        # an N-character "c" string. The remaining 4 deltas the fake
        # stream would have produced never reached the wire and so never
        # accumulated.
        assert persisted[0]["text"] == "c" * N
        assert isinstance(persisted[0]["block_id"], str)
        # The block_id matches the one announced on ``block_start``.
        block_starts = [e for e in wire_events if isinstance(e, BlockStart)]
        assert persisted[0]["block_id"] == block_starts[0].block["block_id"]
        # The Anthropic call kicked off but never completed
        # ``get_final_message()``, so no model_invocation row is recorded.
        repo_mocks["record_model_invocation"].assert_not_awaited()

    async def test_disconnect_check_returning_false_completes_normally(
        self, repo_mocks
    ):
        # When the client stays connected throughout, the loop runs to
        # ``end_turn`` and emits ``turn_completed`` — no cancellation
        # path is exercised.
        client = _make_client(_make_response(text="hi"))
        check_calls = 0

        async def disconnect() -> bool:
            nonlocal check_calls
            check_calls += 1
            return False

        em = SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))
        try:
            result = await run_agent_turn(
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                user_message="hello",
                anthropic_client=client,
                db_factory=_make_db_factory(),
                tool_registry=EMPTY_REGISTRY,
                http_clients=ToolHttpClients(),
                system_prompt=SYSTEM_PROMPT,
                model_config=ModelConfig(model_id=MODEL_ID),
                hard_caps=HardCaps(),
                langfuse=_NoopLangfuse(),
                environment="test",
                sse_emitter=em,
                disconnect_check=disconnect,
            )
        finally:
            await em.close()
        events = await drain_task

        assert result.terminal_state == "end_turn"
        # At least one poll happens (the iteration-boundary check); no
        # mid-stream poll because the response only had one delta.
        assert check_calls >= 1
        terminals = [
            e for e in events if isinstance(e, (TurnCompleted, Error))
        ]
        assert len(terminals) == 1
        assert isinstance(terminals[0], TurnCompleted)
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "end_turn"
        assert kwargs["error_code"] is None

    async def test_external_task_cancel_lands_as_cancelled_terminal_state(
        self, repo_mocks
    ):
        # External-cancellation path: the framework cancels the driver
        # task while the loop is inside the try/except (e.g. when the SSE
        # asyncgen is closed by FastAPI before our poll fires). The same
        # ``except asyncio.CancelledError`` branch must set
        # ``terminal_state='cancelled'`` so the audit row is consistent
        # regardless of which side detected the disconnect first.
        #
        # Park the runner at an await *inside* the try block by using a
        # ``queue_size=1`` emitter and not draining it: ``turn_started``
        # is emitted before the try block (filling the queue), then
        # ``block_start`` — emitted from inside the chunk loop — blocks
        # forever on ``queue.put``. ``task.cancel()`` lands at that await,
        # which is inside the try/except.
        client = _make_client(_make_response(text="hi"))
        em = SSEEmitter(queue_size=1)

        async def runner() -> None:
            await run_agent_turn(
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                user_message="hello",
                anthropic_client=client,
                db_factory=_make_db_factory(),
                tool_registry=EMPTY_REGISTRY,
                http_clients=ToolHttpClients(),
                system_prompt=SYSTEM_PROMPT,
                model_config=ModelConfig(model_id=MODEL_ID),
                hard_caps=HardCaps(),
                langfuse=_NoopLangfuse(),
                environment="test",
                sse_emitter=em,
            )

        task = asyncio.create_task(runner())
        # ``AsyncMock`` and ``asyncio.Queue.put`` on a non-full queue both
        # complete without yielding, so the task only suspends when the
        # queue fills. One yield is enough for the runner to sprint to the
        # second emit (block_start) and park there.
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Drain on cleanup so the queued turn_started doesn't leak.
        drain_task = asyncio.create_task(_drain(em))
        await em.close()
        await drain_task

        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "cancelled"
        assert kwargs["error_code"] == ErrorCode.CANCELLED.value


# ---------- B3.3 (Part B): outer try/finally covers early DB writes ----------


class TestOuterCancellation:
    """Cancellation can land at *any* await — including the early DB writes
    that run before the loop's main while True. The outer
    ``try / except CancelledError / finally`` in ``run_agent_turn``
    guarantees:

    * If ``start_agent_turn`` succeeded → the agent_turn row is finalised
      with ``terminal_state='cancelled'`` no matter where the cancel
      landed (between the row open and the loop, inside the loop's
      pre-Anthropic setup, etc.).
    * If ``start_agent_turn`` never ran → no orphan row to finalise; the
      user_message row (if it persisted) remains durable on its own.

    Without this widened envelope, framework-driven cancellation (e.g.
    sse-starlette closing the asyncgen on client disconnect) would leave
    rows stuck in non-terminal state forever — observed in CLOUD testing
    and the regression this change fixes.
    """

    async def test_cancel_after_start_agent_turn_persists_cancelled_state(
        self, repo_mocks
    ):
        # Cancellation lands AFTER ``start_agent_turn`` (so ``turn_id`` is
        # set) but BEFORE the loop's inner try block. The most realistic
        # await for this is the ``turn_started`` SSE emit. We force a
        # CancelledError there by patching the emitter.
        client = _make_client(_make_response())

        em = SSEEmitter()
        original_emit = em.emit
        emit_calls = 0

        async def cancelling_emit(event):
            nonlocal emit_calls
            emit_calls += 1
            # First emit (TurnStarted) is the one fired before the loop
            # enters its inner try. Cancel exactly there.
            if emit_calls == 1:
                raise asyncio.CancelledError
            await original_emit(event)

        em.emit = cancelling_emit  # type: ignore[method-assign]

        with pytest.raises(asyncio.CancelledError):
            await run_agent_turn(
                user_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                user_message="hello",
                anthropic_client=client,
                db_factory=_make_db_factory(),
                tool_registry=EMPTY_REGISTRY,
                http_clients=ToolHttpClients(),
                system_prompt=SYSTEM_PROMPT,
                model_config=ModelConfig(model_id=MODEL_ID),
                hard_caps=HardCaps(),
                langfuse=_NoopLangfuse(),
                environment="test",
                sse_emitter=em,
            )

        # Anthropic was never called (loop body never entered).
        client.messages.stream.assert_not_called()
        # But the agent_turn row IS finalised with 'cancelled' — the new
        # outer finally writes the row even though the cancellation
        # landed before the inner try.
        repo_mocks["complete_agent_turn"].assert_awaited_once()
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "cancelled"
        assert kwargs["error_code"] == ErrorCode.CANCELLED.value
        assert kwargs["assistant_message_id"] is None
        assert kwargs["iterations_count"] == 0
        repo_mocks["append_assistant_message"].assert_not_awaited()
        repo_mocks["record_model_invocation"].assert_not_awaited()

    async def test_cancel_during_user_message_persist_skips_row_finalize(
        self, repo_mocks
    ):
        # Cancellation lands BEFORE ``start_agent_turn`` runs — there is
        # no agent_turn row to finalise, so ``complete_agent_turn`` must
        # not be called. The CancelledError still propagates to the
        # caller.
        client = _make_client(_make_response())

        async def cancelling_append(*args, **kwargs):
            raise asyncio.CancelledError

        repo_mocks["append_user_message"].side_effect = cancelling_append

        em = SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))
        try:
            with pytest.raises(asyncio.CancelledError):
                await run_agent_turn(
                    user_id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    user_message="hello",
                    anthropic_client=client,
                    db_factory=_make_db_factory(),
                    tool_registry=EMPTY_REGISTRY,
                    http_clients=ToolHttpClients(),
                    system_prompt=SYSTEM_PROMPT,
                    model_config=ModelConfig(model_id=MODEL_ID),
                    hard_caps=HardCaps(),
                    langfuse=_NoopLangfuse(),
                    environment="test",
                    sse_emitter=em,
                )
        finally:
            await em.close()
        await drain_task

        # No agent_turn row ever opened, so no completion row to write.
        repo_mocks["start_agent_turn"].assert_not_awaited()
        repo_mocks["complete_agent_turn"].assert_not_awaited()
        repo_mocks["append_assistant_message"].assert_not_awaited()
        client.messages.stream.assert_not_called()

    async def test_non_cancel_exception_during_early_db_write_marks_error(
        self, repo_mocks
    ):
        # A non-CancelledError exception during early DB writes (e.g. a
        # transient asyncpg error during ``start_agent_turn``) should
        # still propagate to the caller. The outer finally's defensive
        # guard handles ``terminal_state=None`` — but with no agent_turn
        # row, there is nothing to finalise. The exception bubbles up.
        client = _make_client(_make_response())

        async def failing_start(*args, **kwargs):
            raise RuntimeError("transient db failure")

        repo_mocks["start_agent_turn"].side_effect = failing_start

        em = SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))
        try:
            with pytest.raises(RuntimeError, match="transient db failure"):
                await run_agent_turn(
                    user_id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    user_message="hello",
                    anthropic_client=client,
                    db_factory=_make_db_factory(),
                    tool_registry=EMPTY_REGISTRY,
                    http_clients=ToolHttpClients(),
                    system_prompt=SYSTEM_PROMPT,
                    model_config=ModelConfig(model_id=MODEL_ID),
                    hard_caps=HardCaps(),
                    langfuse=_NoopLangfuse(),
                    environment="test",
                    sse_emitter=em,
                )
        finally:
            await em.close()
        await drain_task

        # User message was persisted (the await before start_agent_turn
        # completed). The row that failed to open isn't there to
        # finalise, so complete_agent_turn isn't called.
        repo_mocks["append_user_message"].assert_awaited_once()
        repo_mocks["complete_agent_turn"].assert_not_awaited()


# ---------- Anthropic server tools ----------


class TestAnthropicServerTools:

    async def test_no_tools_kwarg_when_no_server_tools_enabled_and_empty_registry(
        self, repo_mocks
    ):
        client = _make_client(_make_response())

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(),
        )

        create_kwargs = client.messages.stream.call_args.kwargs
        assert "tools" not in create_kwargs

    async def test_web_search_spec_prepended(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(
                web_search_enabled=True,
                web_search_max_uses=3,
            ),
        )

        create_kwargs = client.messages.stream.call_args.kwargs
        # No cache marker — tools cache via the system-prompt breakpoint.
        assert create_kwargs["tools"] == [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }
        ]

    async def test_all_three_server_tools_enabled(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(
                web_search_enabled=True,
                web_fetch_enabled=True,
                code_execution_enabled=True,
                web_search_max_uses=2,
                web_fetch_max_uses=4,
            ),
        )

        create_kwargs = client.messages.stream.call_args.kwargs
        assert create_kwargs["tools"] == [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 2,
            },
            {
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": 4,
            },
            {
                "type": "code_execution_20250825",
                "name": "code_execution",
            },
        ]

    async def test_server_tools_prepended_before_registry(self, repo_mocks):
        registry_spec = [
            {"name": "get_stock_info", "description": "...", "input_schema": {}},
        ]

        class _Reg:
            @property
            def is_empty(self) -> bool:
                return False

            def to_anthropic_spec(self) -> list[dict[str, Any]]:
                return registry_spec

        client = _make_client(_make_response())

        await _run(
            client,
            repo_mocks,
            tool_registry=_Reg(),
            server_tools_config=ServerToolsConfig(
                web_search_enabled=True,
                web_search_max_uses=5,
            ),
        )

        create_kwargs = client.messages.stream.call_args.kwargs
        assert create_kwargs["tools"] == [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5,
            },
            {
                "name": "get_stock_info",
                "description": "...",
                "input_schema": {},
            },
        ]

    async def test_writes_audit_row_for_web_search_call(self, repo_mocks):
        from anthropic.types import (
            ServerToolUseBlock,
            WebSearchToolResultBlock,
        )
        from anthropic.types.web_search_result_block import WebSearchResultBlock

        server_use = ServerToolUseBlock(
            id="srvtoolu_1",
            input={"query": "AMD earnings today"},
            name="web_search",
            type="server_tool_use",
        )
        search_result = WebSearchToolResultBlock(
            tool_use_id="srvtoolu_1",
            content=[
                WebSearchResultBlock(
                    encrypted_content="enc1",
                    title="AMD posts strong Q3",
                    type="web_search_result",
                    url="https://example.com/amd-q3",
                )
            ],
            type="web_search_tool_result",
        )
        response = _make_response(
            text="AMD posted strong Q3 numbers today.",
            extra_blocks=[server_use, search_result],
        )
        client = _make_client(response)

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        repo_mocks["record_tool_execution"].assert_awaited_once()
        kwargs = repo_mocks["record_tool_execution"].call_args.kwargs
        assert kwargs["tool_name"] == "anthropic:web_search"
        assert kwargs["tool_use_id"] == "srvtoolu_1"
        assert kwargs["input_payload"] == {"query": "AMD earnings today"}
        assert kwargs["status"] == "success"
        assert kwargs.get("internal_trace") is None
        assert kwargs["output_payload"] is not None
        assert "content" in kwargs["output_payload"]

    async def test_writes_audit_row_for_web_fetch_error(self, repo_mocks):
        from anthropic.types import ServerToolUseBlock, WebFetchToolResultBlock
        from anthropic.types.web_fetch_tool_result_error_block import (
            WebFetchToolResultErrorBlock,
        )

        server_use = ServerToolUseBlock(
            id="srvtoolu_2",
            input={"url": "https://blocked.example.com"},
            name="web_fetch",
            type="server_tool_use",
        )
        error_result = WebFetchToolResultBlock(
            tool_use_id="srvtoolu_2",
            content=WebFetchToolResultErrorBlock(
                error_code="url_not_allowed",
                type="web_fetch_tool_result_error",
            ),
            type="web_fetch_tool_result",
        )
        response = _make_response(
            text="Couldn't fetch that URL.",
            extra_blocks=[server_use, error_result],
        )
        client = _make_client(response)

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_fetch_enabled=True),
        )

        repo_mocks["record_tool_execution"].assert_awaited_once()
        kwargs = repo_mocks["record_tool_execution"].call_args.kwargs
        assert kwargs["tool_name"] == "anthropic:web_fetch"
        assert kwargs["status"] == "error"
        assert kwargs["error_message"] == "url_not_allowed"
        assert kwargs["output_payload"] is None

    async def test_no_audit_rows_when_server_tools_disabled(self, repo_mocks):
        client = _make_client(_make_response(text="plain text response"))

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(),
        )

        repo_mocks["record_tool_execution"].assert_not_awaited()

    async def test_writes_audit_row_for_code_execution_success(self, repo_mocks):
        from anthropic.types import (
            CodeExecutionToolResultBlock,
            ServerToolUseBlock,
        )
        from anthropic.types.code_execution_result_block import (
            CodeExecutionResultBlock,
        )

        server_use = ServerToolUseBlock(
            id="srvtoolu_code",
            input={"code": "print(2 + 2)"},
            name="code_execution",
            type="server_tool_use",
        )
        success_result = CodeExecutionToolResultBlock(
            tool_use_id="srvtoolu_code",
            content=CodeExecutionResultBlock(
                content=[],
                return_code=0,
                stderr="",
                stdout="4\n",
                type="code_execution_result",
            ),
            type="code_execution_tool_result",
        )
        response = _make_response(
            text="2 + 2 = 4",
            extra_blocks=[server_use, success_result],
        )
        client = _make_client(response)

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(
                code_execution_enabled=True,
            ),
        )

        repo_mocks["record_tool_execution"].assert_awaited_once()
        kwargs = repo_mocks["record_tool_execution"].call_args.kwargs
        assert kwargs["tool_name"] == "anthropic:code_execution"
        assert kwargs["status"] == "success"
        assert kwargs["input_payload"] == {"code": "print(2 + 2)"}
        assert kwargs["output_payload"] is not None
        assert "content" in kwargs["output_payload"]

    async def test_logs_warning_when_server_tool_use_missing_result_block(
        self, repo_mocks, caplog
    ):
        from anthropic.types import ServerToolUseBlock

        server_use = ServerToolUseBlock(
            id="srvtoolu_orphan",
            input={"query": "test"},
            name="web_search",
            type="server_tool_use",
        )
        response = _make_response(
            text="couldn't search",
            extra_blocks=[server_use],
        )
        client = _make_client(response)

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        repo_mocks["record_tool_execution"].assert_awaited_once()
        kwargs = repo_mocks["record_tool_execution"].call_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_message"] == "missing_result_block"

    async def test_emits_status_pill_events_for_web_search(self, repo_mocks):
        from anthropic.types import (
            ServerToolUseBlock,
            WebSearchToolResultBlock,
        )
        from anthropic.types.web_search_result_block import WebSearchResultBlock

        server_use = ServerToolUseBlock(
            id="srvtoolu_search",
            input={"query": "AMD earnings"},
            name="web_search",
            type="server_tool_use",
        )
        search_result = WebSearchToolResultBlock(
            tool_use_id="srvtoolu_search",
            content=[
                WebSearchResultBlock(
                    encrypted_content="enc",
                    title="AMD beats",
                    type="web_search_result",
                    url="https://example.com",
                )
            ],
            type="web_search_tool_result",
        )
        response = _make_response(
            text="Per the earnings beat…",
            extra_blocks=[server_use, search_result],
        )
        client = _make_client(response)

        _, events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        assert len(status_starts) == 1
        start = status_starts[0]
        assert start.block["state"] == "active"
        assert start.block["label"] == "Searching the web"
        assert isinstance(start.block["block_id"], str) and start.block["block_id"]

        status_block_id = start.block["block_id"]
        data_events = [
            e
            for e in events
            if isinstance(e, BlockData) and e.block_id == status_block_id
        ]
        assert len(data_events) == 1
        assert data_events[0].data == {"state": "complete"}
        end_events = [
            e
            for e in events
            if isinstance(e, BlockEnd) and e.block_id == status_block_id
        ]
        assert len(end_events) == 1

    async def test_status_pill_state_failed_on_result_error(self, repo_mocks):
        from anthropic.types import ServerToolUseBlock, WebFetchToolResultBlock
        from anthropic.types.web_fetch_tool_result_error_block import (
            WebFetchToolResultErrorBlock,
        )

        server_use = ServerToolUseBlock(
            id="srvtoolu_fail",
            input={"url": "https://blocked.example.com"},
            name="web_fetch",
            type="server_tool_use",
        )
        error_result = WebFetchToolResultBlock(
            tool_use_id="srvtoolu_fail",
            content=WebFetchToolResultErrorBlock(
                error_code="url_not_allowed",
                type="web_fetch_tool_result_error",
            ),
            type="web_fetch_tool_result",
        )
        response = _make_response(
            text="Couldn't fetch.",
            extra_blocks=[server_use, error_result],
        )
        client = _make_client(response)

        _, events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_fetch_enabled=True),
        )

        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        assert len(status_starts) == 1
        assert status_starts[0].block["label"] == "Fetching webpage"
        data_events = [e for e in events if isinstance(e, BlockData)]
        assert len(data_events) == 1
        assert data_events[0].data == {"state": "failed"}

    async def test_status_pill_persisted_to_message_blocks(self, repo_mocks):
        from anthropic.types import (
            ServerToolUseBlock,
            WebSearchToolResultBlock,
        )
        from anthropic.types.web_search_result_block import WebSearchResultBlock

        server_use = ServerToolUseBlock(
            id="srvtoolu_persist",
            input={"query": "test"},
            name="web_search",
            type="server_tool_use",
        )
        search_result = WebSearchToolResultBlock(
            tool_use_id="srvtoolu_persist",
            content=[
                WebSearchResultBlock(
                    encrypted_content="enc",
                    title="t",
                    type="web_search_result",
                    url="https://example.com",
                )
            ],
            type="web_search_tool_result",
        )
        response = _make_response(
            text="Found it.",
            extra_blocks=[server_use, search_result],
        )
        client = _make_client(response)

        await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        kwargs = repo_mocks["append_assistant_message"].call_args.kwargs
        blocks = kwargs["content_blocks"]
        types = [b["type"] for b in blocks]
        assert "status" in types
        assert "text" in types
        status_block = next(b for b in blocks if b["type"] == "status")
        assert status_block["state"] == "complete"
        assert status_block["label"] == "Searching the web"
        assert isinstance(status_block["block_id"], str)

    async def test_no_status_pill_events_when_server_tools_disabled(
        self, repo_mocks
    ):
        from anthropic.types import ServerToolUseBlock

        server_use = ServerToolUseBlock(
            id="srvtoolu_x",
            input={"query": "x"},
            name="web_search",
            type="server_tool_use",
        )
        response = _make_response(
            text="hi", extra_blocks=[server_use]
        )
        client = _make_client(response)

        _, events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(),
        )

        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        assert status_starts == []
        data_events = [e for e in events if isinstance(e, BlockData)]
        assert data_events == []

    async def test_cross_iteration_pill_closes_when_result_lands_later(
        self, repo_mocks, monkeypatch
    ):
        # The bug: when Anthropic returns a server_tool_use AND a custom
        # tool_use in iter 0, the search result is deferred to iter 1.
        # The status pill should still flip to complete when the result
        # arrives in iter 1, and the audit row should reflect success.
        from anthropic.types import (
            ServerToolUseBlock,
            ToolUseBlock,
            WebSearchToolResultBlock,
        )
        from anthropic.types.web_search_result_block import WebSearchResultBlock

        from app.ai.runtime.loop import _ToolDispatchOutcome

        # Iter 0: server_tool_use + custom tool_use, stop_reason=tool_use
        iter0 = _make_response(
            text="thinking about AMD",
            stop_reason="tool_use",
            extra_blocks=[
                ToolUseBlock(
                    id="toolu_custom",
                    name="get_stock_info",
                    input={"symbol": "AMD"},
                    type="tool_use",
                ),
                ServerToolUseBlock(
                    id="srvtoolu_deferred",
                    input={"query": "AMD news"},
                    name="web_search",
                    type="server_tool_use",
                ),
            ],
        )
        # Iter 1: web_search_tool_result for the iter-0 use + text
        iter1 = _make_response(
            text="Based on the search…",
            stop_reason="end_turn",
            extra_blocks=[
                WebSearchToolResultBlock(
                    tool_use_id="srvtoolu_deferred",
                    content=[
                        WebSearchResultBlock(
                            encrypted_content="enc",
                            title="AMD beats",
                            type="web_search_result",
                            url="https://example.com",
                        )
                    ],
                    type="web_search_tool_result",
                )
            ],
        )

        # Stub out custom-tool dispatch so iter 0 → iter 1 cleanly without
        # needing a real ToolRegistry with a working get_stock_info.
        async def _stub_dispatch(**kwargs: Any) -> _ToolDispatchOutcome:
            outcome = _ToolDispatchOutcome()
            outcome.tool_call_count = 1
            outcome.tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_custom",
                    "content": "{\"ok\": true}",
                }
            )
            return outcome

        monkeypatch.setattr(
            "app.ai.runtime.flow.iteration.dispatch_tool_uses", _stub_dispatch
        )

        client = _make_client([iter0, iter1])

        result, events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2

        # Pill events fired across iterations: one BlockStart(active) in
        # iter 0, one BlockData(complete) + BlockEnd in iter 1.
        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        assert len(status_starts) == 1
        status_block_id = status_starts[0].block["block_id"]
        assert status_starts[0].block["state"] == "active"

        data_events = [
            e
            for e in events
            if isinstance(e, BlockData) and e.block_id == status_block_id
        ]
        assert len(data_events) == 1
        assert data_events[0].data == {"state": "complete"}

        end_events = [
            e
            for e in events
            if isinstance(e, BlockEnd) and e.block_id == status_block_id
        ]
        assert len(end_events) == 1

        # Audit row: status=success with the original input from iter 0.
        # Find the row keyed on the server tool's tool_use_id (other rows
        # may exist for the custom tool dispatch — though our stub
        # bypasses record_tool_execution for that path).
        server_audit_calls = [
            c
            for c in repo_mocks["record_tool_execution"].call_args_list
            if c.kwargs.get("tool_use_id") == "srvtoolu_deferred"
        ]
        assert len(server_audit_calls) == 1
        kwargs = server_audit_calls[0].kwargs
        assert kwargs["tool_name"] == "anthropic:web_search"
        assert kwargs["status"] == "success"
        assert kwargs["error_message"] is None
        assert kwargs["input_payload"] == {"query": "AMD news"}
        assert kwargs["output_payload"] is not None

        # Persisted assistant message has the pill in its terminal state.
        msg_kwargs = (
            repo_mocks["append_assistant_message"].call_args.kwargs
        )
        status_blocks = [
            b for b in msg_kwargs["content_blocks"] if b["type"] == "status"
        ]
        assert len(status_blocks) == 1
        assert status_blocks[0]["state"] == "complete"

    async def test_replay_scrubs_server_tool_result_before_next_model_call(
        self, repo_mocks, monkeypatch
    ):
        from anthropic.types import (
            ServerToolUseBlock,
            ToolUseBlock,
            WebSearchToolResultBlock,
        )
        from anthropic.types.web_search_result_block import WebSearchResultBlock

        from app.ai.runtime.loop import _ToolDispatchOutcome

        server_use = ServerToolUseBlock.model_construct(
            id="srvtoolu_dirty",
            input={"query": "AMD news"},
            name="web_search",
            type="server_tool_use",
            caller={"type": "direct"},
        )
        dirty_search_result = WebSearchToolResultBlock.model_construct(
            type="web_search_tool_result",
            tool_use_id="srvtoolu_dirty",
            caller={"type": "direct"},
            parsed_output={"sdk": True},
            text="output-only top-level text",
            content=[
                WebSearchResultBlock.model_construct(
                    type="web_search_result",
                    title="AMD beats",
                    url="https://example.com/amd",
                    encrypted_content="enc",
                    text="output-only nested text",
                    citations=[{"url": "https://example.com/amd"}],
                )
            ],
        )
        iter0 = _make_response(
            text="checking",
            stop_reason="tool_use",
            extra_blocks=[
                server_use,
                dirty_search_result,
                ToolUseBlock(
                    id="toolu_custom",
                    name="get_stock_info",
                    input={"symbol": "AMD"},
                    type="tool_use",
                ),
            ],
        )
        iter1 = _make_response(text="done", stop_reason="end_turn")

        async def _stub_dispatch(**kwargs: Any) -> _ToolDispatchOutcome:
            outcome = _ToolDispatchOutcome()
            outcome.tool_call_count = 1
            outcome.tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_custom",
                    "content": "{\"ok\": true}",
                }
            )
            return outcome

        monkeypatch.setattr(
            "app.ai.runtime.flow.iteration.dispatch_tool_uses", _stub_dispatch
        )

        client = _make_client([iter0, iter1])
        captured_messages: list[list[dict[str, Any]]] = []
        original_stream = client.messages.stream

        def capture_stream(**kwargs: Any) -> Any:
            captured_messages.append(json.loads(json.dumps(kwargs["messages"])))
            return original_stream(**kwargs)

        client.messages.stream = MagicMock(side_effect=capture_stream)

        result, _events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2
        assert len(captured_messages) == 2

        replayed_assistant = captured_messages[1][-2]
        assert replayed_assistant["role"] == "assistant"
        replayed_content = replayed_assistant["content"]
        replayed_server_use = next(
            b for b in replayed_content if b["type"] == "server_tool_use"
        )
        assert replayed_server_use == {
            "type": "server_tool_use",
            "id": "srvtoolu_dirty",
            "name": "web_search",
            "input": {"query": "AMD news"},
        }
        replayed_result = next(
            b for b in replayed_content if b["type"] == "web_search_tool_result"
        )
        assert replayed_result == {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_dirty",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "AMD beats",
                    "url": "https://example.com/amd",
                    "encrypted_content": "enc",
                    "page_age": None,
                }
            ],
        }

        replayed_user = captured_messages[1][-1]
        assert replayed_user["role"] == "user"
        assert replayed_user["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_custom",
                "content": "{\"ok\": true}",
            }
        ]

    async def test_orphan_pill_closes_failed_when_result_never_arrives(
        self, repo_mocks
    ):
        # If a server_tool_use lands but no matching result block ever
        # arrives (turn ends with stop_reason=end_turn), the orphan-flush
        # path closes the pill as failed and writes an error audit row.
        from anthropic.types import ServerToolUseBlock

        response = _make_response(
            text="orphan",
            extra_blocks=[
                ServerToolUseBlock(
                    id="srvtoolu_orphan",
                    input={"query": "test"},
                    name="web_search",
                    type="server_tool_use",
                )
            ],
        )
        client = _make_client(response)

        _, events = await _run(
            client,
            repo_mocks,
            server_tools_config=ServerToolsConfig(web_search_enabled=True),
        )

        status_starts = [
            e
            for e in events
            if isinstance(e, BlockStart) and e.block.get("type") == "status"
        ]
        assert len(status_starts) == 1
        status_block_id = status_starts[0].block["block_id"]

        data_events = [
            e
            for e in events
            if isinstance(e, BlockData) and e.block_id == status_block_id
        ]
        assert len(data_events) == 1
        assert data_events[0].data == {"state": "failed"}

        end_events = [
            e
            for e in events
            if isinstance(e, BlockEnd) and e.block_id == status_block_id
        ]
        assert len(end_events) == 1

        kwargs = repo_mocks["record_tool_execution"].call_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["error_message"] == "missing_result_block"

        msg_kwargs = (
            repo_mocks["append_assistant_message"].call_args.kwargs
        )
        status_blocks = [
            b for b in msg_kwargs["content_blocks"] if b["type"] == "status"
        ]
        assert len(status_blocks) == 1
        assert status_blocks[0]["state"] == "failed"

    async def test_cancel_flips_active_pill_to_failed(self, repo_mocks):
        # If the turn is cancelled while a pill is still in flight, the
        # persisted message must not show a phantom spinner on reload —
        # the cancel handler flips active pills to failed in place.
        from anthropic.types import ServerToolUseBlock

        N = 16  # _DISCONNECT_CHECK_DELTA_INTERVAL
        text_chunks = ["c"] * (N + 4)
        full_text = "".join(text_chunks)
        server_use = ServerToolUseBlock(
            id="srvtoolu_cancel",
            input={"query": "test"},
            name="web_search",
            type="server_tool_use",
        )
        final = _make_response(
            text=full_text, extra_blocks=[server_use]
        )

        # Stream: server_tool_use lands first (pill emitted active), then
        # N+4 text deltas. disconnect_check trips after the Nth delta, the
        # loop raises CancelledError before the result block can arrive.
        from anthropic.types import (
            ServerToolUseBlock as ServerToolUseBlockType,
        )

        events_list: list[Any] = [
            RawContentBlockStartEvent(
                content_block=ServerToolUseBlockType(
                    id="srvtoolu_cancel",
                    input={"query": "test"},
                    name="web_search",
                    type="server_tool_use",
                ),
                index=0,
                type="content_block_start",
            ),
            RawContentBlockStopEvent(
                index=0, type="content_block_stop"
            ),
            RawContentBlockStartEvent(
                content_block=TextBlock(text="", type="text"),
                index=1,
                type="content_block_start",
            ),
            *[
                RawContentBlockDeltaEvent(
                    delta=AnthropicTextDelta(text=c, type="text_delta"),
                    index=1,
                    type="content_block_delta",
                )
                for c in text_chunks
            ],
            RawContentBlockStopEvent(
                index=1, type="content_block_stop"
            ),
        ]
        client = MagicMock(spec=anthropic.AsyncAnthropic)
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(_FakeStream(events_list, final))
        )

        check_calls = 0

        async def disconnect() -> bool:
            nonlocal check_calls
            check_calls += 1
            return check_calls > 1

        em = SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))
        try:
            with pytest.raises(asyncio.CancelledError):
                await run_agent_turn(
                    user_id=uuid.uuid4(),
                    conversation_id=uuid.uuid4(),
                    user_message="hello",
                    anthropic_client=client,
                    db_factory=_make_db_factory(),
                    tool_registry=EMPTY_REGISTRY,
                    http_clients=ToolHttpClients(),
                    system_prompt=SYSTEM_PROMPT,
                    model_config=ModelConfig(model_id=MODEL_ID),
                    hard_caps=HardCaps(),
                    langfuse=_NoopLangfuse(),
                    environment="test",
                    sse_emitter=em,
                    disconnect_check=disconnect,
                    server_tools_config=ServerToolsConfig(
                        web_search_enabled=True
                    ),
                )
        finally:
            await em.close()
        await drain_task

        # The persisted assistant message has the pill flipped to failed,
        # not stuck in active.
        msg_kwargs = (
            repo_mocks["append_assistant_message"].call_args.kwargs
        )
        status_blocks = [
            b for b in msg_kwargs["content_blocks"] if b["type"] == "status"
        ]
        assert len(status_blocks) == 1
        assert status_blocks[0]["state"] == "failed"


# ---------- user_context: two decoupled channels (SEV-615) ----------


def _history_user_msg(*content_blocks: dict[str, Any]) -> Any:
    """A persisted user ``Message`` stand-in for ``load_history`` mocks.

    ``initialize_turn`` reloads history to build ``messages``; the current
    turn is always its newest row, so faithful tests echo the just-persisted
    blocks back here rather than the default empty list.
    """
    return type(
        "M", (), {"role": "user", "content_blocks": list(content_blocks)}
    )()


def _capture_messages(client: Any) -> dict[str, Any]:
    """Snapshot the ``messages`` arg of the *first* ``messages.stream`` call.

    The loop appends assistant turns after the response returns, so capturing
    at call time is the only way to see exactly what the model received.
    """
    captured: dict[str, Any] = {}
    original_stream = client.messages.stream

    def capture(**kwargs: Any) -> Any:
        if "messages" not in captured:
            captured["messages"] = [
                {"role": m["role"], "content": list(m["content"])}
                for m in kwargs["messages"]
            ]
        return original_stream(**kwargs)

    client.messages.stream = MagicMock(side_effect=capture)
    return captured


class TestUserContext:
    # SEV-615: ``user_context`` drives two decoupled channels.
    #   UI channel    — a typed ``ContextBlock`` persisted in
    #                    ``content_blocks`` (restores the chip on resume).
    #   Model channel — a short ``render_hint`` appended to the current
    #                    turn's messages; ``kind``-driven plus a whitelisted
    #                    non-stale field (the portfolio chart's range), never
    #                    the frozen numeric ``data``, never replayed later.

    async def test_persists_typed_context_block_after_text_block(
        self, repo_mocks
    ):
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "t", "text": "what's this?"}
            )
        ]
        client = _make_client(_make_response())
        ctx = AttachedContextRequest(
            kind=ContextKind.PORTFOLIO, data={"equity": "12500.50"}
        )

        await _run(
            client, repo_mocks, user_message="what's this?", user_context=ctx
        )

        kwargs = repo_mocks["append_user_message"].call_args.kwargs
        blocks = kwargs["content_blocks"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "text"
        assert blocks[0]["text"] == "what's this?"
        # The persisted block is the typed ``ContextBlock`` dump: ``kind``
        # is the plain enum *value* (not the enum repr) and ``data`` rides
        # through opaque for the iOS chip.
        assert blocks[1]["type"] == "context"
        assert blocks[1]["kind"] == "portfolio"
        assert blocks[1]["data"] == {"equity": "12500.50"}
        # Both blocks carry server-minted ULIDs for iOS resume correlation.
        assert isinstance(blocks[0]["block_id"], str) and blocks[0]["block_id"]
        assert isinstance(blocks[1]["block_id"], str) and blocks[1]["block_id"]
        assert blocks[0]["block_id"] != blocks[1]["block_id"]

    async def test_no_context_block_when_user_context_none(self, repo_mocks):
        # The default path mints only the text block. Regression guard
        # against accidentally appending an empty context block.
        client = _make_client(_make_response())

        await _run(client, repo_mocks, user_message="hello")

        kwargs = repo_mocks["append_user_message"].call_args.kwargs
        blocks = kwargs["content_blocks"]
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    async def test_context_block_persisted_even_with_empty_data(
        self, repo_mocks
    ):
        # The guard is ``user_context is not None`` — an attachment with
        # empty ``data`` is still a valid attachment (hint + chip are
        # ``kind``-driven), so it persists a context block.
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "t", "text": "hello"}
            )
        ]
        client = _make_client(_make_response())
        ctx = AttachedContextRequest(kind=ContextKind.RADAR)

        await _run(client, repo_mocks, user_message="hello", user_context=ctx)

        kwargs = repo_mocks["append_user_message"].call_args.kwargs
        blocks = kwargs["content_blocks"]
        assert len(blocks) == 2
        assert blocks[1]["type"] == "context"
        assert blocks[1]["kind"] == "radar"
        assert blocks[1]["data"] == {}

    async def test_current_turn_injects_kind_hint_after_user_text(
        self, repo_mocks
    ):
        # Model channel: the current turn's user message gets the short hint
        # appended after the user text. The portfolio hint surfaces the
        # whitelisted ``time_range`` ("1M" -> "1-month") but never the frozen
        # ``equity`` snapshot, which would be stale.
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "t", "text": "how am I doing?"},
                {
                    "type": "context",
                    "block_id": "c",
                    "kind": "portfolio",
                    "data": {"equity": "12500.50", "time_range": "1M"},
                },
            )
        ]
        client = _make_client(_make_response())
        captured = _capture_messages(client)

        await _run(
            client,
            repo_mocks,
            user_message="how am I doing?",
            user_context=AttachedContextRequest(
                kind=ContextKind.PORTFOLIO,
                data={"equity": "12500.50", "time_range": "1M"},
            ),
        )

        user_blocks = captured["messages"][-1]["content"]
        assert user_blocks[0] == {"type": "text", "text": "how am I doing?"}
        assert user_blocks[-1] == {
            "type": "text",
            "text": (
                "The user is currently viewing their portfolio, with the "
                "value chart set to the 1-month range. This screen shows "
                "their total account value and the gain or loss over that "
                "range on an interactive value-over-time chart. Their message "
                "may be referring to a figure, trend, or the selected period "
                "shown here."
            ),
        }
        # The selected range is surfaced; the frozen snapshot value is not.
        assert "1-month" in json.dumps(captured["messages"])
        assert "12500.50" not in json.dumps(captured["messages"])

    async def test_no_hint_injected_when_user_context_none(self, repo_mocks):
        # Without an attachment the current turn carries only the user text.
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "t", "text": "plain question"}
            )
        ]
        client = _make_client(_make_response())
        captured = _capture_messages(client)

        await _run(client, repo_mocks, user_message="plain question")

        assert captured["messages"][-1]["content"] == [
            {"type": "text", "text": "plain question"}
        ]

    async def test_reloaded_context_block_is_not_replayed(self, repo_mocks):
        # A *prior* turn's persisted context block must not re-enter the
        # model input on a later turn — ``to_anthropic_content`` drops it,
        # leaving only that turn's user text.
        repo_mocks["load_history"].return_value = [
            _history_user_msg(
                {"type": "text", "block_id": "x", "text": "what's AAPL"},
                {
                    "type": "context",
                    "block_id": "y",
                    "kind": "holdings",
                    "data": {"holdings": [{"ticker": "AAPL"}]},
                },
            )
        ]
        client = _make_client(_make_response())
        captured = _capture_messages(client)

        # No ``user_context`` on *this* turn → no hint; the reloaded block
        # is dropped, leaving just the prior user text.
        await _run(client, repo_mocks)

        history_messages = captured["messages"]
        assert len(history_messages) == 1
        assert history_messages[0]["content"] == [
            {"type": "text", "text": "what's AAPL"}
        ]
        assert "AAPL" in history_messages[0]["content"][0]["text"]


# ---------- non-error terminal stop reasons ----------


class TestStopReasonRoutingNonError:
    # The catch-all branch in ``_decide_after_response`` records
    # ``stop_reason`` verbatim into ``terminal_state`` with no error code.
    # This means refusal, stop_sequence, and unknown future values flow
    # through as ``TurnCompleted`` (not ``Error``) — which can mask
    # safety incidents from monitoring.

    async def test_refusal_records_terminal_state_without_error_code(
        self, repo_mocks
    ):
        # Anthropic's safety-refusal stop_reason. The loop currently
        # treats it as a normal completion (no error_code), so iOS sees
        # ``TurnCompleted``. If a future change wants to route this as
        # an ``Error``, this test must be updated alongside it.
        client = _make_client(_make_response(stop_reason="refusal"))

        result, events = await _run(client, repo_mocks)

        assert result.terminal_state == "refusal"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "refusal"
        assert kwargs["error_code"] is None
        # iOS sees ``TurnCompleted`` — not ``Error``. This is the
        # documented (if surprising) current behavior.
        terminal_events = [
            e for e in events if isinstance(e, (TurnCompleted, Error))
        ]
        assert len(terminal_events) == 1
        assert isinstance(terminal_events[0], TurnCompleted)
        assert terminal_events[0].terminal_state == "refusal"

    async def test_stop_sequence_records_terminal_state_without_error_code(
        self, repo_mocks
    ):
        # User-defined stop sequence hit. Same routing as refusal.
        client = _make_client(_make_response(stop_reason="stop_sequence"))

        result, events = await _run(client, repo_mocks)

        assert result.terminal_state == "stop_sequence"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] is None
        terminal_events = [
            e for e in events if isinstance(e, (TurnCompleted, Error))
        ]
        assert len(terminal_events) == 1
        assert isinstance(terminal_events[0], TurnCompleted)

    async def test_none_stop_reason_falls_back_to_unknown(self, repo_mocks):
        # Defensive ``or "unknown"`` branch — a None stop_reason should
        # never reach us from a real API call, but the fallback prevents
        # ``terminal_state=None`` from corrupting the row.
        response = Message(
            id="msg_no_stop",
            content=[TextBlock(text="hi", type="text")],
            model=MODEL_ID,
            role="assistant",
            stop_reason=None,
            type="message",
            usage=Usage(input_tokens=5, output_tokens=2),
        )
        client = _make_client(response)

        result, _events = await _run(client, repo_mocks)

        assert result.terminal_state == "unknown"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["terminal_state"] == "unknown"
        assert kwargs["error_code"] is None


# ---------- block_id correlation fallback ----------


class TestBlockIdFallback:
    # The streamed ``content_block_start`` mints the ULID that iOS uses to
    # correlate every subsequent ``text_delta`` and ``block_end`` event
    # back to the persisted assistant block. If a text block lands in
    # ``response.content`` without a matching ``content_block_start``
    # (SDK glitch / partial stream / race), the loop mints a *new* ULID
    # for persistence — diverging from the wire. iOS correlation breaks.
    # This is the primary documented failure mode for resume.

    async def test_missing_stream_event_mints_fallback_block_id(
        self, repo_mocks, monkeypatch
    ):
        # Build a client whose stream emits NO content_block_start events
        # but whose final_message DOES contain a text block. This is the
        # exact SDK-drift case the fallback is defending against.
        text_content = "hello"
        final_message = Message(
            id="msg_drift",
            content=[TextBlock(text=text_content, type="text")],
            model=MODEL_ID,
            role="assistant",
            stop_reason="end_turn",
            type="message",
            usage=Usage(input_tokens=5, output_tokens=2),
        )

        client = MagicMock(spec=anthropic.AsyncAnthropic)
        # Empty event list → ``open_text_blocks`` stays empty during
        # streaming. ``get_final_message`` still returns the block.
        client.messages.stream = MagicMock(
            return_value=_FakeStreamManager(_FakeStream([], final_message))
        )

        warnings: list[tuple[str, dict[str, Any]]] = []
        from app.ai.runtime.flow import iteration as iteration_module

        original_warning = iteration_module.logger.warning

        def capture_warning(event: str, **kwargs: Any) -> None:
            warnings.append((event, kwargs))
            original_warning(event, **kwargs)

        monkeypatch.setattr(
            iteration_module.logger, "warning", capture_warning
        )

        result, events = await _run(client, repo_mocks)

        # The persisted assistant block has a freshly-minted ULID, NOT
        # whatever (none) was streamed.
        assert len(result.assistant_message_blocks) == 1
        persisted_block = result.assistant_message_blocks[0]
        assert persisted_block["type"] == "text"
        assert persisted_block["text"] == text_content
        persisted_block_id = persisted_block["block_id"]
        assert isinstance(persisted_block_id, str) and persisted_block_id

        # iOS never received a ``BlockStart`` for the fallback id, so
        # the assertion is: no streamed event uses the persisted id.
        streamed_block_starts = [
            e for e in events if isinstance(e, BlockStart)
        ]
        for event in streamed_block_starts:
            assert event.block.get("block_id") != persisted_block_id

        # The fallback path MUST log loudly. If this warning ever stops
        # firing, operators lose the only signal that correlation broke.
        fallback_warnings = [
            (name, kw)
            for (name, kw) in warnings
            if name == "loop_text_block_id_fallback"
        ]
        assert len(fallback_warnings) == 1
        _, log_kwargs = fallback_warnings[0]
        # Tags carry the debugging context we'd need to diagnose.
        assert "turn_id" in log_kwargs
        assert log_kwargs["iteration_index"] == 0
        assert log_kwargs["response_index"] == 0
        assert log_kwargs["streamed_indices"] == []


# ---------- shielded finalize ----------


class TestShieldedFinalize:
    # The outer finally wraps ``finalize_turn_row`` in ``asyncio.shield``
    # specifically because sse-starlette re-cancels tasks during teardown.
    # Without the shield, ``complete_agent_turn`` would be cancelled
    # mid-COMMIT and the row would never close. This test forces the
    # exact race: the loop enters finalize → COMMIT is in flight → the
    # task is cancelled. With the shield, COMMIT lands; without it, the
    # mock is never fully awaited.

    async def test_cancel_during_finalize_does_not_truncate_commit(
        self, repo_mocks
    ):
        client = _make_client(_make_response())

        in_finalize = asyncio.Event()
        finalize_done = asyncio.Event()

        async def slow_complete(*args: Any, **kwargs: Any) -> None:
            in_finalize.set()
            # ``shield`` masks the parent cancellation while this sleeps.
            # Without the shield, this sleep would raise CancelledError
            # and the row would never close.
            await asyncio.sleep(0.05)
            finalize_done.set()

        repo_mocks["complete_agent_turn"].side_effect = slow_complete

        em = SSEEmitter()
        drain_task = asyncio.create_task(_drain(em))

        kwargs: dict[str, Any] = {
            "user_id": uuid.uuid4(),
            "conversation_id": uuid.uuid4(),
            "user_message": "hello",
            "anthropic_client": client,
            "db_factory": _make_db_factory(),
            "tool_registry": EMPTY_REGISTRY,
            "http_clients": ToolHttpClients(),
            "system_prompt": SYSTEM_PROMPT,
            "model_config": ModelConfig(model_id=MODEL_ID),
            "hard_caps": HardCaps(),
            "langfuse": _NoopLangfuse(),
            "environment": "test",
            "sse_emitter": em,
        }
        loop_task = asyncio.create_task(run_agent_turn(**kwargs))

        # Wait for the loop to enter ``complete_agent_turn``.
        await asyncio.wait_for(in_finalize.wait(), timeout=2.0)

        # Cancel the loop task RIGHT NOW — while ``complete_agent_turn``
        # is mid-await. The shield must keep the awaitable alive until
        # it returns; only then should ``CancelledError`` propagate.
        loop_task.cancel()

        # ``finalize_done`` setting is the proof that the COMMIT
        # actually completed despite the cancel landing during it.
        await asyncio.wait_for(finalize_done.wait(), timeout=2.0)

        with pytest.raises(asyncio.CancelledError):
            await loop_task

        await em.close()
        await drain_task

        repo_mocks["complete_agent_turn"].assert_awaited_once()


# ---------- finalize_turn_row exception swallow ----------


class TestFinalizeRowExceptionSwallow:
    # ``finalize_turn_row`` wraps the assistant-message append and
    # ``complete_agent_turn`` in ``try/except Exception`` and logs
    # rather than re-raising. By the time finalize runs, the only
    # signal the agent_turn row can give is its terminal_state — if
    # finalize itself raised, the loop's outer finally would have no
    # downstream catch and the failure would surface as a 500 to the
    # client. The swallow is intentional, but it carries the cost of
    # silent compound failures: a successful assistant-message append
    # followed by a failing complete_agent_turn leaves an orphan row
    # with only a log line as a signal.

    async def test_complete_agent_turn_failure_does_not_propagate(
        self, repo_mocks, monkeypatch
    ):
        # Loop returns the normal ``AgentTurnResult`` even though the
        # final commit failed. Operators see the log; the caller does
        # not see an exception. This is the contract — any regression
        # that propagates would change a recoverable mid-turn failure
        # into a HTTP 500.
        repo_mocks["complete_agent_turn"].side_effect = RuntimeError(
            "db gone"
        )

        warnings_captured: list[tuple[str, dict[str, Any]]] = []
        from app.ai.runtime.flow import turn_lifecycle

        monkeypatch.setattr(
            turn_lifecycle.logger,
            "exception",
            lambda event, **kw: warnings_captured.append((event, kw)),
        )

        client = _make_client(_make_response())
        result, _events = await _run(client, repo_mocks)

        # The result is the normal end_turn result — no propagation.
        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 1

        # The compound-failure path MUST log loudly so operators see
        # the orphan turn row signal.
        finalize_errors = [
            (name, kw)
            for (name, kw) in warnings_captured
            if name == "agent_turn_finalize_failed"
        ]
        assert len(finalize_errors) == 1
        _, log_kwargs = finalize_errors[0]
        assert log_kwargs["terminal_state"] == "end_turn"
        assert "turn_id" in log_kwargs

    async def test_append_assistant_message_failure_does_not_propagate(
        self, repo_mocks, monkeypatch
    ):
        # The first DB write inside finalize. If this raises, the
        # ``complete_agent_turn`` call never happens — the agent_turn
        # row stays non-terminal. The log line is operators' only
        # signal.
        repo_mocks["append_assistant_message"].side_effect = RuntimeError(
            "db gone"
        )

        warnings_captured: list[tuple[str, dict[str, Any]]] = []
        from app.ai.runtime.flow import turn_lifecycle

        monkeypatch.setattr(
            turn_lifecycle.logger,
            "exception",
            lambda event, **kw: warnings_captured.append((event, kw)),
        )

        client = _make_client(_make_response())
        result, _events = await _run(client, repo_mocks)

        # The loop returns normally even though the assistant message
        # never persisted.
        assert result.terminal_state == "end_turn"
        # ``complete_agent_turn`` was never called — the exception in
        # append_assistant_message aborted the rest of finalize.
        repo_mocks["complete_agent_turn"].assert_not_awaited()
        # But the log fired.
        assert any(
            name == "agent_turn_finalize_failed"
            for (name, _kw) in warnings_captured
        )

    async def test_orphan_assistant_message_when_complete_agent_turn_fails(
        self, repo_mocks, monkeypatch
    ):
        # The compound-failure case the audit flagged: assistant
        # message persists, but the turn-row link never lands. iOS
        # would see a TurnCompleted (loop succeeds) while the DB shows
        # a non-terminal agent_turn pointing at a freshly-persisted
        # message. Only the log connects the two.
        repo_mocks["complete_agent_turn"].side_effect = RuntimeError("db")

        from app.ai.runtime.flow import turn_lifecycle

        monkeypatch.setattr(
            turn_lifecycle.logger, "exception", lambda *a, **kw: None
        )

        client = _make_client(_make_response())
        result, _events = await _run(client, repo_mocks)

        # Assistant message DID land.
        repo_mocks["append_assistant_message"].assert_awaited_once()
        # complete_agent_turn was attempted and raised.
        repo_mocks["complete_agent_turn"].assert_awaited_once()
        # Loop returned normally — the orphan state is invisible
        # to the caller.
        assert result.terminal_state == "end_turn"
