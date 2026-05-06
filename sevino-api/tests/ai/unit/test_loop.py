"""Unit tests for ``run_agent_turn``.

The agent loop is exercised end-to-end with a fake Anthropic client and a
fake DB factory whose context manager yields a recording stub. Persistence
side-effects are asserted against ``ConversationRepository`` call captures
(the repository itself is integration-tested separately in
``tests/ai/integration/test_conversation_repo.py``).
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

from app.ai.prompts import SystemPrompt
from app.ai.runtime.caps import HardCaps
from app.ai.runtime.errors import ErrorCode
from app.ai.runtime.loop import run_agent_turn
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig, ToolRegistry

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


def _make_client(response_or_exc: Any) -> AsyncMock:
    """Build a fake ``AsyncAnthropic`` whose ``messages.create`` returns
    ``response_or_exc`` (or raises if it's an exception). When a list is
    passed, each call yields the next item in order — used to exercise
    multi-iteration loops (A1.7)."""
    client = AsyncMock(spec=anthropic.AsyncAnthropic)
    if isinstance(response_or_exc, BaseException):
        client.messages.create = AsyncMock(side_effect=response_or_exc)
    elif isinstance(response_or_exc, list):
        client.messages.create = AsyncMock(side_effect=response_or_exc)
    else:
        client.messages.create = AsyncMock(return_value=response_or_exc)
    return client


async def _run(
    client: AsyncMock,
    repo_mocks: dict[str, Any],
    *,
    hard_caps: HardCaps | None = None,
    tool_registry: ToolRegistry | None = None,
    user_message: str = "hello",
):
    return await run_agent_turn(
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_message=user_message,
        anthropic_client=client,
        db_factory=_make_db_factory(),
        tool_registry=tool_registry or EMPTY_REGISTRY,
        system_prompt=SYSTEM_PROMPT,
        model_config=ModelConfig(model_id=MODEL_ID),
        hard_caps=hard_caps or HardCaps(),
    )


# ---------- happy path ----------


class TestHappyPath:
    async def test_single_iteration_returns_expected_result(self, repo_mocks):
        client = _make_client(_make_response(text="hi there"))

        result = await _run(client, repo_mocks)

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 1
        assert result.assistant_message_blocks == [
            {"type": "text", "text": "hi there"}
        ]
        assert result.total_cost_usd_micros > 0
        client.messages.create.assert_awaited_once()

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
        assert kwargs["content_blocks"] == [
            {"type": "text", "text": "visible answer"}
        ]


# ---------- request shape ----------


class TestRequestShape:
    async def test_tools_kwarg_omitted_when_registry_empty(self, repo_mocks):
        client = _make_client(_make_response())

        await _run(client, repo_mocks)

        create_kwargs = client.messages.create.call_args.kwargs
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

        create_kwargs = client.messages.create.call_args.kwargs
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

        create_kwargs = client.messages.create.call_args.kwargs
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

        create_kwargs = client.messages.create.call_args.kwargs
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

        result = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_iterations=0)
        )

        assert result.terminal_state == "iteration_limit"
        assert result.iterations_count == 0
        assert result.assistant_message_blocks == []
        client.messages.create.assert_not_awaited()
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

        result = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_wall_clock_s=10.0)
        )

        assert result.terminal_state == "timeout"
        client.messages.create.assert_not_awaited()

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

        result = await _run(
            client, repo_mocks, hard_caps=HardCaps(max_output_tokens=1100)
        )

        assert result.terminal_state == "output_token_limit"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.OUTPUT_TOKEN_LIMIT.value
        # Only one Anthropic call: iteration 2's cap check fires before
        # the second create() would have been issued.
        client.messages.create.assert_awaited_once()

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
        client.messages.create.assert_not_awaited()


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

        result = await _run(client, repo_mocks)

        assert result.terminal_state == "end_turn"
        assert result.iterations_count == 2
        assert client.messages.create.await_count == 2

    async def test_iteration_two_request_includes_iteration_one_thinking(
        self, repo_mocks
    ):
        # The R1 contract: model_invocations.response_content from
        # iteration N is what gets passed back as iteration N+1's assistant
        # message — never reconstructed. Verify the thinking block (with
        # signature) survives the roundtrip byte-for-byte.
        #
        # The loop reuses (and mutates) one ``messages`` list across
        # iterations, so AsyncMock's call-args recording — which holds the
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

        async def _side_effect(**kwargs: Any) -> Message:
            captured_messages.append(copy.deepcopy(kwargs["messages"]))
            return responses[len(captured_messages) - 1]

        client = AsyncMock(spec=anthropic.AsyncAnthropic)
        client.messages.create = AsyncMock(side_effect=_side_effect)

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

        result = await _run(client, repo_mocks)

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

        result = await _run(client, repo_mocks)

        assert result.terminal_state == "output_token_limit"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.OUTPUT_TOKEN_LIMIT.value

    async def test_unexpected_tool_use_in_v0_marks_internal_error(
        self, repo_mocks
    ):
        # No tools are registered, but Anthropic returned tool_use anyway —
        # treat as misconfiguration.
        client = _make_client(_make_response(stop_reason="tool_use"))

        result = await _run(client, repo_mocks)

        assert result.terminal_state == "error"
        kwargs = repo_mocks["complete_agent_turn"].call_args.kwargs
        assert kwargs["error_code"] == ErrorCode.INTERNAL_ERROR.value
