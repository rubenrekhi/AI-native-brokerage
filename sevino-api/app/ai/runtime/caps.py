import time
from dataclasses import dataclass
from enum import Enum

from app.ai.runtime.types import LoopState

__all__ = ["CapBreach", "HardCaps", "LoopState", "check_caps"]


class CapBreach(str, Enum):
    """Values written to `agent_turns.terminal_state` when a cap ends a turn."""

    ITERATION_LIMIT = "iteration_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    TIMEOUT = "timeout"
    OUTPUT_TOKEN_LIMIT = "output_token_limit"


@dataclass(frozen=True, slots=True)
class HardCaps:
    max_iterations: int = 10
    max_tool_calls: int = 20
    max_wall_clock_s: float = 60.0
    max_output_tokens: int = 2048


def check_caps(
    state: LoopState,
    caps: HardCaps,
    *,
    now: float | None = None,
) -> CapBreach | None:
    if state.iterations >= caps.max_iterations:
        return CapBreach.ITERATION_LIMIT
    if state.tool_calls >= caps.max_tool_calls:
        return CapBreach.TOOL_CALL_LIMIT
    elapsed = (now if now is not None else time.monotonic()) - state.started_at_monotonic
    if elapsed >= caps.max_wall_clock_s:
        return CapBreach.TIMEOUT
    if state.output_tokens >= caps.max_output_tokens:
        return CapBreach.OUTPUT_TOKEN_LIMIT
    return None
