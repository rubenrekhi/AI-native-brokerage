import time
from dataclasses import FrozenInstanceError

import pytest

from app.ai.runtime.caps import CapBreach, HardCaps, check_caps
from app.ai.runtime.types import LoopState


class TestHardCaps:
    def test_v0_default_values(self):
        caps = HardCaps()
        assert caps.max_iterations == 10
        assert caps.max_tool_calls == 20
        assert caps.max_wall_clock_s == 60.0
        assert caps.max_output_tokens == 2048

    def test_is_frozen(self):
        caps = HardCaps()
        with pytest.raises(FrozenInstanceError):
            caps.max_iterations = 5  # type: ignore[misc]


class TestCapBreach:
    def test_values_match_documented_terminal_state(self):
        # These strings land in agent_turns.terminal_state — must match
        # ai-v0-plan.md (A1.4) so future schema/migration changes stay aligned.
        assert CapBreach.ITERATION_LIMIT.value == "iteration_limit"
        assert CapBreach.TOOL_CALL_LIMIT.value == "tool_call_limit"
        assert CapBreach.TIMEOUT.value == "timeout"
        assert CapBreach.OUTPUT_TOKEN_LIMIT.value == "output_token_limit"


class TestCheckCaps:
    def test_returns_none_when_under_all_limits(self):
        caps = HardCaps()
        state = LoopState(
            iterations=5,
            tool_calls=10,
            output_tokens=1000,
            started_at_monotonic=100.0,
        )
        assert check_caps(state, caps, now=120.0) is None

    def test_iteration_limit_breached_at_max(self):
        caps = HardCaps(max_iterations=3)
        state = LoopState(iterations=3, started_at_monotonic=0.0)
        assert check_caps(state, caps, now=0.0) is CapBreach.ITERATION_LIMIT

    def test_iteration_one_below_max_passes(self):
        caps = HardCaps(max_iterations=3)
        state = LoopState(iterations=2, started_at_monotonic=0.0)
        assert check_caps(state, caps, now=0.0) is None

    def test_tool_call_limit_breached_at_max(self):
        caps = HardCaps(max_tool_calls=2)
        state = LoopState(tool_calls=2, started_at_monotonic=0.0)
        assert check_caps(state, caps, now=0.0) is CapBreach.TOOL_CALL_LIMIT

    def test_timeout_breached_at_wall_clock(self):
        caps = HardCaps(max_wall_clock_s=60.0)
        state = LoopState(started_at_monotonic=0.0)
        assert check_caps(state, caps, now=60.0) is CapBreach.TIMEOUT

    def test_timeout_just_below_passes(self):
        caps = HardCaps(max_wall_clock_s=60.0)
        state = LoopState(started_at_monotonic=0.0)
        assert check_caps(state, caps, now=59.999) is None

    def test_output_token_limit_breached_at_max(self):
        caps = HardCaps(max_output_tokens=100)
        state = LoopState(output_tokens=100, started_at_monotonic=0.0)
        assert check_caps(state, caps, now=0.0) is CapBreach.OUTPUT_TOKEN_LIMIT

    def test_iteration_breach_reported_first_when_multiple_caps_violated(self):
        # Precedence locked in: iteration_limit is the most informative signal
        # for debugging stuck tool-call loops, which is what caps exist to catch.
        caps = HardCaps(
            max_iterations=1,
            max_tool_calls=1,
            max_wall_clock_s=1.0,
            max_output_tokens=1,
        )
        state = LoopState(
            iterations=10,
            tool_calls=10,
            output_tokens=10,
            started_at_monotonic=0.0,
        )
        assert check_caps(state, caps, now=100.0) is CapBreach.ITERATION_LIMIT

    def test_default_now_uses_monotonic_clock(self):
        caps = HardCaps(max_wall_clock_s=60.0)
        state = LoopState(started_at_monotonic=time.monotonic() - 100)
        assert check_caps(state, caps) is CapBreach.TIMEOUT
