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
from typing import Any, Protocol


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

    The full ``Tool`` / ``ToolContext`` framework lands in Project C; v0
    callers pass :data:`EMPTY_REGISTRY` and the loop skips the ``tools``
    arg in the Anthropic request entirely (Anthropic 400s on an empty
    tools array, so we send no key rather than an empty list).
    """

    @property
    def is_empty(self) -> bool: ...

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None: ...


class _EmptyRegistry:
    """No-op ``ToolRegistry`` used in v0 where the loop has no tools."""

    @property
    def is_empty(self) -> bool:
        return True

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None:
        return None


EMPTY_REGISTRY: ToolRegistry = _EmptyRegistry()
