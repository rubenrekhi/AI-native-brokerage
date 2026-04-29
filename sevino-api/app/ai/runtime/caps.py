import time
from dataclasses import dataclass, field
from enum import Enum


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


@dataclass(slots=True)
class LoopState:
    """Minimal counters `check_caps` reads to evaluate hard caps.

    Lives here for A1.4 so the cap helper is testable in isolation. When A1.6
    lands `app/ai/runtime/types.py`, move `LoopState` there and have the loop's
    turn state compose around it rather than extend it in place — keep
    `caps.py` focused on cap checks.
    """

    iterations: int = 0
    tool_calls: int = 0
    output_tokens: int = 0
    started_at_monotonic: float = field(default_factory=time.monotonic)


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
