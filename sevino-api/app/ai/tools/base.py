"""Tool framework: ABC, result, context, and registry.

Per AI v0 plan C1.1 (sevino-api/docs/ai-v0-plan.md). This module is the
single API the team adds tools through — every new tool is one
``Tool`` subclass plus one ``ToolRegistry.register(...)`` call.

Layout intentionally self-contained: the Anthropic spec produced by
:meth:`ToolRegistry.to_anthropic_spec` includes the A1.8
``cache_control`` marker on the trailing tool, so the agent loop hands
the result to ``messages.create`` verbatim. C1.2 wires ``ToolContext``
into the loop; this ticket only ships the surface.

``ToolContext.parent_emitter`` exists from day one — the trade-flow
sub-agent (post-v0) is the same agent loop called with a different
registry + system prompt, and a child agent's events bubble up via
``parent_emitter`` so the parent's stream sees the child's blocks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.blocks import Block
from app.ai.runtime.db import DbSessionFactory
from app.ai.transport.events import Event

__all__ = [
    "SSEEmitter",
    "Tool",
    "ToolContext",
    "ToolHttpClients",
    "ToolRegistry",
    "ToolResult",
]


# Static-typing surface for the streaming emitter passed to tools. The
# concrete implementation is provided by the chat-turn endpoint (Project
# B) — keeping it as a Protocol here means ``app/ai/tools`` does not
# depend on the transport layer and tests can pass a trivial fake.
class SSEEmitter(Protocol):
    """Awaitable sink for SSE events bound to the active turn's stream."""

    async def emit(self, event: Event) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolHttpClients:
    """Holder for HTTP / service clients tools may need.

    Empty in C1.1 — fields are added as service tickets land (C2.2 brings
    ``alpaca_market_data`` for the ``get_stock_info`` tool). Frozen so a
    tool cannot mutate the shared client bundle mid-turn.
    """


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Per-turn dependencies handed to ``Tool.execute``.

    ``db_factory`` is the session-per-write factory from
    :mod:`app.ai.runtime.db` (decision D12) — tools that need to
    persist must open their own short transaction inside execute,
    rather than holding a session for the duration of the tool call.

    ``parent_emitter`` is reserved for sub-agent flows: a sub-agent
    receives its parent's emitter here so events emitted into its own
    stream can also bubble up to the parent's UI. ``None`` in v0
    (top-level turns only).
    """

    user_id: UUID
    db_factory: DbSessionFactory
    sse_emitter: SSEEmitter
    http_clients: ToolHttpClients
    parent_emitter: SSEEmitter | None = None


class ToolResult(BaseModel):
    """Return value of ``Tool.execute``.

    Three lanes carrying the same tool call to three audiences:

    * ``model_payload`` — the JSON the tool result block sent back to
      Anthropic. Keep this small; Anthropic re-tokenises it on every
      iteration of the loop.
    * ``ui_block`` — optional :data:`~app.ai.blocks.Block` rendered in
      the chat surface. ``None`` for tools whose output is purely
      model-facing.
    * ``internal_trace`` — verbatim upstream payloads / debug data
      written to ``tool_executions.internal_trace`` (never sent to the
      model, never rendered to the user).

    Pydantic-backed so the whole struct round-trips JSON cleanly —
    ``ui_block`` rides through the discriminated union and decodes back
    to the right ``Block`` subclass. ``protected_namespaces=()`` is
    required because ``model_payload`` collides with Pydantic's
    reserved ``model_*`` namespace.
    """

    model_config = ConfigDict(protected_namespaces=())

    model_payload: dict[str, Any]
    ui_block: Block | None = Field(default=None)
    internal_trace: dict[str, Any] | None = None


InputT = TypeVar("InputT", bound=BaseModel)


class Tool(ABC, Generic[InputT]):
    """Base class for every agent tool.

    Subclasses set three class-level attributes (``name``,
    ``description``, ``Input``) and implement async ``execute``.
    The Anthropic-side description is what the model reads to decide
    when to call the tool — write it for the model, not for humans.

    ``Input`` is a Pydantic model class. The agent loop validates the
    raw arguments Anthropic emits via ``Input.model_validate(...)``
    before calling ``execute`` (C1.2), so ``execute`` always receives a
    fully-typed input.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(self, input: InputT, ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    """Name-indexed collection of registered tools.

    The registry is built once at app startup, populated via
    :meth:`register`, and handed to ``run_agent_turn`` per call.

    :meth:`to_anthropic_spec` returns the tool definitions array Claude
    expects — name + description + the ``Input`` model's JSON schema.
    Per A1.8, the trailing entry carries ``cache_control: {"type":
    "ephemeral"}`` so the entire tools array caches alongside the
    system prompt. Caller can pass the result straight to
    ``messages.create``.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        """Add ``tool`` to the registry, keyed by ``tool.name``.

        Raises ``ValueError`` on duplicate name — silently overwriting
        a registered tool would mask configuration bugs.
        """
        name = tool.name
        if name in self._tools:
            raise ValueError(f"Tool {name!r} is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool[Any]:
        """Look up a tool by name.

        Raises ``KeyError`` when the name is unknown — callers
        (currently the agent loop) treat this as a hard error and map
        it to ``ErrorCode.INTERNAL_ERROR``.
        """
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Tool {name!r} is not registered") from exc

    @property
    def is_empty(self) -> bool:
        """Whether any tools are registered.

        Anthropic 400s on an empty ``tools`` array, so the loop checks
        this before forwarding the spec.
        """
        return not self._tools

    def to_anthropic_spec(self) -> list[dict[str, Any]]:
        """Build the tool definitions array for ``messages.create``.

        Returns an empty list when no tools are registered. Otherwise,
        the trailing entry carries the A1.8 cache_control marker so the
        whole tools array (together with the system block) is treated
        as one cacheable prefix on every turn within the 5m TTL.
        """
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
        specs[-1] = {**specs[-1], "cache_control": {"type": "ephemeral"}}
        return specs
