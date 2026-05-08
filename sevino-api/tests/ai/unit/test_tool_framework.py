"""Unit tests for ``app.ai.tools.base`` (SEV-494 / C1.1).

Acceptance criteria from the AI v0 plan:

* Register a fake tool, retrieve via registry, ``to_anthropic_spec``
  produces the right shape.
* ``ToolResult`` round-trips JSON.
* ``ToolContext.parent_emitter`` exists from day one (sub-agent hook).
"""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.ai.blocks import StatusBlock, TextBlock
from app.ai.tools import (
    SSEEmitter,
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)


class _EchoInput(BaseModel):
    message: str


class _EchoTool(Tool[_EchoInput]):
    name: ClassVar[str] = "echo"
    description: ClassVar[str] = "Echo the input message back to the model."
    Input: ClassVar[type[BaseModel]] = _EchoInput

    async def execute(
        self, input: _EchoInput, ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(model_payload={"echoed": input.message})


class _AnotherInput(BaseModel):
    n: int


class _AnotherTool(Tool[_AnotherInput]):
    name: ClassVar[str] = "another"
    description: ClassVar[str] = "Returns the doubled integer."
    Input: ClassVar[type[BaseModel]] = _AnotherInput

    async def execute(
        self, input: _AnotherInput, ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(model_payload={"value": input.n * 2})


class TestToolRegistryRegisterAndGet:
    def test_register_then_get_returns_same_instance(self):
        registry = ToolRegistry()
        tool = _EchoTool()

        registry.register(tool)

        assert registry.get("echo") is tool

    def test_get_unknown_name_raises_key_error(self):
        registry = ToolRegistry()

        with pytest.raises(KeyError, match="not registered"):
            registry.get("missing")

    def test_register_duplicate_name_raises(self):
        # Silent overwrite would mask startup-time wiring bugs — surface
        # the conflict loudly so the dev fixes it before the app boots.
        registry = ToolRegistry()
        registry.register(_EchoTool())

        with pytest.raises(ValueError, match="already registered"):
            registry.register(_EchoTool())

    def test_empty_registry_reports_is_empty(self):
        # ``is_empty`` is the gate the agent loop uses to decide whether
        # to send the ``tools`` key on the Anthropic request — Anthropic
        # 400s on an empty array, so an empty registry must skip it.
        registry = ToolRegistry()

        assert registry.is_empty is True
        assert registry.to_anthropic_spec() == []

    def test_populated_registry_reports_not_empty(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())

        assert registry.is_empty is False


class TestToAnthropicSpec:
    def test_single_tool_spec_includes_name_description_input_schema_and_cache(
        self,
    ):
        registry = ToolRegistry()
        registry.register(_EchoTool())

        [spec] = registry.to_anthropic_spec()

        assert spec["name"] == "echo"
        assert spec["description"] == _EchoTool.description
        # ``input_schema`` is the pydantic JSON schema for ``Input``.
        assert spec["input_schema"] == _EchoInput.model_json_schema()
        # A1.8: trailing tool carries the ephemeral cache marker so the
        # tools array caches alongside the system prompt.
        assert spec["cache_control"] == {"type": "ephemeral"}

    def test_multiple_tools_only_last_carries_cache_control(self):
        # Anthropic caches everything up to and including the marker —
        # placing it on any earlier tool would shrink the cached prefix.
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.register(_AnotherTool())

        specs = registry.to_anthropic_spec()

        assert [s["name"] for s in specs] == ["echo", "another"]
        assert "cache_control" not in specs[0]
        assert specs[1]["cache_control"] == {"type": "ephemeral"}

    def test_spec_calls_are_independent(self):
        # Calling ``to_anthropic_spec`` twice must not accumulate
        # cache_control on earlier tools — the loop reads the spec once
        # per turn and we want each turn's request to be identical.
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.register(_AnotherTool())

        first = registry.to_anthropic_spec()
        second = registry.to_anthropic_spec()

        assert first == second
        assert "cache_control" not in second[0]


class TestToolResultJsonRoundTrip:
    def test_payload_only_round_trip(self):
        original = ToolResult(model_payload={"price": 123.45, "symbol": "AMD"})

        restored = ToolResult.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.ui_block is None
        assert restored.internal_trace is None

    def test_round_trip_preserves_ui_block_variant(self):
        # Discriminator on ``ui_block`` must dispatch back to the right
        # ``Block`` subclass after JSON round-trip.
        original = ToolResult(
            model_payload={"label": "ok"},
            ui_block=StatusBlock(
                block_id="blk_1", label="Looking up AMD", state="active"
            ),
            internal_trace={"raw": {"foo": "bar"}},
        )

        restored = ToolResult.model_validate_json(original.model_dump_json())

        assert isinstance(restored.ui_block, StatusBlock)
        assert restored == original

    def test_round_trip_with_text_block(self):
        original = ToolResult(
            model_payload={},
            ui_block=TextBlock(block_id="blk_2", text="hello"),
        )

        restored = ToolResult.model_validate_json(original.model_dump_json())

        assert isinstance(restored.ui_block, TextBlock)
        assert restored == original


class TestToolContextShape:
    def test_parent_emitter_field_exists_and_defaults_to_none(self):
        # The plan calls out ``parent_emitter`` as a day-one field even
        # though no v0 caller populates it — the trade-flow sub-agent
        # post-v0 needs it without a context-shape change.
        emitter: SSEEmitter = MagicMock()

        ctx = ToolContext(
            user_id=uuid4(),
            db_factory=MagicMock(),
            sse_emitter=emitter,
            http_clients=ToolHttpClients(),
        )

        assert hasattr(ctx, "parent_emitter")
        assert ctx.parent_emitter is None

    def test_parent_emitter_can_be_provided(self):
        parent: SSEEmitter = MagicMock()

        ctx = ToolContext(
            user_id=uuid4(),
            db_factory=MagicMock(),
            sse_emitter=MagicMock(),
            http_clients=ToolHttpClients(),
            parent_emitter=parent,
        )

        assert ctx.parent_emitter is parent


class TestToolAbcEnforcement:
    def test_cannot_instantiate_tool_without_execute(self):
        # ABC guard: subclasses that forget ``execute`` are caught at
        # instantiation rather than at first call.
        class _Incomplete(Tool[_EchoInput]):
            name: ClassVar[str] = "incomplete"
            description: ClassVar[str] = "."
            Input: ClassVar[type[BaseModel]] = _EchoInput

        with pytest.raises(TypeError):
            _Incomplete()  # type: ignore[abstract]
