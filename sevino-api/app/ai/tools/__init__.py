"""Tool framework public API + default registry.

Re-exports the surface from :mod:`app.ai.tools.base`. Concrete tools live
in sibling modules (``stock_info`` etc.) and are wired into the default
registry by :func:`build_default_registry`, which the chat-turn route
hands to the agent loop.
"""

from app.ai.tools.base import (
    SSEEmitter,
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)
from app.ai.tools.display_stock_card import (
    DisplayStockCard,
    DisplayStockCardInput,
)
from app.ai.tools.stock_info import GetStockInfo, StockInfoInput

__all__ = [
    "SSEEmitter",
    "Tool",
    "ToolContext",
    "ToolHttpClients",
    "ToolRegistry",
    "ToolResult",
    "DisplayStockCard",
    "DisplayStockCardInput",
    "GetStockInfo",
    "StockInfoInput",
    "build_default_registry",
    "DEFAULT_REGISTRY",
]


def build_default_registry() -> ToolRegistry:
    """Return a fresh registry populated with every shipped tool.

    Called once at module import to build :data:`DEFAULT_REGISTRY`. Tests
    that want a clean slate can call this themselves instead of importing
    the module-level constant.
    """
    registry = ToolRegistry()
    registry.register(GetStockInfo())
    registry.register(DisplayStockCard())
    return registry


DEFAULT_REGISTRY: ToolRegistry = build_default_registry()
