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
from app.ai.tools.radar_operations import RadarOperations, RadarOperationsInput
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
    "RadarOperations",
    "RadarOperationsInput",
    "build_default_registry",
    "DEFAULT_REGISTRY",
]


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GetStockInfo())
    registry.register(DisplayStockCard())
    registry.register(RadarOperations())
    return registry


DEFAULT_REGISTRY: ToolRegistry = build_default_registry()
