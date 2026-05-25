"""Input / output types for the agent runtime.

Per AI v0 plan A1.6 (sevino-api/docs/ai-v0-plan.md): types live here so the
loop module stays focused on orchestration. ``LoopState`` moved here from
``caps.py`` so loop-specific turn state can compose around it without
extending the cap-check surface.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.ai.tools.base import Tool


@dataclass(slots=True)
class LoopState:
    """Counters consumed by ``check_caps`` to evaluate hard caps."""

    iterations: int = 0
    tool_calls: int = 0
    output_tokens: int = 0
    started_at_monotonic: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Per-turn Anthropic model configuration.

    Single field for v0; future fields (temperature, top_k, thinking budget)
    can be added without changing the loop signature.
    """

    model_id: str


@dataclass(frozen=True, slots=True)
class ServerToolsConfig:
    """Anthropic server-side tools to advertise to the model."""

    web_search_enabled: bool = False
    web_fetch_enabled: bool = False
    code_execution_enabled: bool = False
    web_search_max_uses: int = 5
    web_fetch_max_uses: int = 5

    @property
    def any_enabled(self) -> bool:
        return (
            self.web_search_enabled
            or self.web_fetch_enabled
            or self.code_execution_enabled
        )


DISABLED_SERVER_TOOLS = ServerToolsConfig()


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    """Return value of ``run_agent_turn``.

    Shape mandated by the AI v0 plan (A1.6). ``terminal_state`` mirrors the
    value persisted on ``agent_turns.terminal_state`` so callers can branch
    without a second DB lookup. ``turn_id`` is the same UUID written to
    ``agent_turns.id`` and surfaced on the SSE wire envelope — exposed on
    the result so the chat-turn endpoint can key idempotency replay (B3.2)
    off it without a second DB lookup.
    """

    turn_id: uuid.UUID
    terminal_state: str
    assistant_message_blocks: list[dict[str, Any]]
    total_cost_usd_micros: int
    iterations_count: int


class ToolRegistry(Protocol):
    """Minimum surface the loop needs to integrate tools.

    Implemented by the concrete ``app.ai.tools.ToolRegistry`` (C1.1) and
    by :class:`_EmptyRegistry` for the no-tools case. The Protocol stays
    here in ``runtime.types`` so the loop never imports the tool
    framework when no tools are registered, and so the chat endpoint
    can hand :data:`EMPTY_REGISTRY` without dragging in
    ``app.ai.tools.base``.

    ``get`` is invoked in C1.2's tool_use branch — the loop looks up the
    tool by the ``name`` Claude returned in a ``tool_use`` block. The
    empty-registry path raises ``KeyError`` here, which the loop maps to
    ``ErrorCode.INTERNAL_ERROR`` (a registered model that calls a tool
    we don't know about is a wiring bug, not a recoverable case).
    """

    @property
    def is_empty(self) -> bool: ...

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None: ...

    def get(self, name: str) -> "Tool[Any]": ...


class _EmptyRegistry:
    """No-op ``ToolRegistry`` used in v0 where the loop has no tools."""

    @property
    def is_empty(self) -> bool:
        return True

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None:
        return None

    def get(self, name: str) -> "Tool[Any]":
        # Reachable only if the loop fails to gate on ``is_empty`` before
        # routing a ``tool_use`` block. Fail loudly so the regression
        # surfaces with the offending tool name instead of a confusing
        # downstream error.
        raise KeyError(f"Tool {name!r} is not registered (registry is empty)")


EMPTY_REGISTRY: ToolRegistry = _EmptyRegistry()
