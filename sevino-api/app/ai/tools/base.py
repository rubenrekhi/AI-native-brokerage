"""Tool framework: ABC, result, context, and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.blocks import Block
from app.ai.runtime.db import DbSessionFactory
from app.ai.transport.events import Event

if TYPE_CHECKING:
    from app.services.market_data import MarketDataService

__all__ = [
    "SSEEmitter",
    "Tool",
    "ToolContext",
    "ToolHttpClients",
    "ToolRegistry",
    "ToolResult",
]


class SSEEmitter(Protocol):
    async def emit(self, event: Event) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolHttpClients:
    # ``market_data`` is None without ``FMP_API_KEY``.
    market_data: "MarketDataService | None" = None


@dataclass(frozen=True, slots=True)
class ToolContext:
    user_id: UUID
    db_factory: DbSessionFactory
    sse_emitter: SSEEmitter
    http_clients: ToolHttpClients
    parent_emitter: SSEEmitter | None = None


class ToolResult(BaseModel):
    """Tool output: model_payload (back to Anthropic), ui_block (to user),
    internal_trace (audit only).
    """

    # ``protected_namespaces=()`` lets us use the ``model_payload`` field name.
    model_config = ConfigDict(protected_namespaces=())

    model_payload: dict[str, Any]
    ui_block: Block | None = Field(default=None)
    internal_trace: dict[str, Any] | None = None


InputT = TypeVar("InputT", bound=BaseModel)


class Tool(ABC, Generic[InputT]):
    """Base class for tools. Set ``name`` / ``description`` / ``Input``
    and implement ``execute``. The loop validates input before calling.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, input: InputT, ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        name = tool.name
        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool[Any]:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Tool {name!r} is not registered") from exc

    @property
    def is_empty(self) -> bool:
        return not self._tools

    def to_anthropic_spec(self) -> list[dict[str, Any]]:
        if not self._tools:
            return []
        specs: list[dict[str, Any]] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.Input.model_json_schema(),
            }
            for tool in self._tools.values()
        ]
        # Cache the tools array alongside the system prompt.
        specs[-1] = {**specs[-1], "cache_control": {"type": "ephemeral"}}
        return specs
