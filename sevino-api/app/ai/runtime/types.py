"""Input / output types for the agent runtime."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.ai.tools.base import Tool


@dataclass(slots=True)
class LoopState:
    iterations: int = 0
    tool_calls: int = 0
    output_tokens: int = 0
    started_at_monotonic: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    model_id: str


@dataclass(frozen=True, slots=True)
class ServerToolsConfig:
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
    turn_id: uuid.UUID
    terminal_state: str
    assistant_message_blocks: list[dict[str, Any]]
    total_cost_usd_micros: int
    iterations_count: int


class ToolRegistry(Protocol):
    """Tool-registry surface the loop depends on.

    Kept here as a Protocol so the loop doesn't import the tool framework
    when no tools are registered.
    """

    @property
    def is_empty(self) -> bool: ...

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None: ...

    def get(self, name: str) -> "Tool[Any]": ...


class _EmptyRegistry:
    @property
    def is_empty(self) -> bool:
        return True

    def to_anthropic_spec(self) -> list[dict[str, Any]] | None:
        return None

    def get(self, name: str) -> "Tool[Any]":
        raise KeyError(f"Tool {name!r} is not registered (registry is empty)")


EMPTY_REGISTRY: ToolRegistry = _EmptyRegistry()
