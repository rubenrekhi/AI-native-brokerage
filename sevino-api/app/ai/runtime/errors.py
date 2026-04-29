"""Error taxonomy for the AI agent runtime.

`ErrorCode` is the closed set of values surfaced on the `error` SSE event
(wired in Phase 2). `to_error_code` collapses any exception raised inside
the agent loop into one of those values.
"""

from __future__ import annotations

import asyncio
from enum import Enum

import anthropic
import pydantic


class ErrorCode(str, Enum):
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_ERROR = "tool_error"
    MODEL_OVERLOADED = "model_overloaded"
    MODEL_RATE_LIMIT = "model_rate_limit"
    INTERNAL_ERROR = "internal_error"
    CANCELLED = "cancelled"
    TURN_ITERATION_LIMIT = "turn_iteration_limit"
    TOOL_CALL_LIMIT = "tool_call_limit"
    OUTPUT_TOKEN_LIMIT = "output_token_limit"
    VALIDATION_ERROR = "validation_error"


def to_error_code(exc: BaseException) -> ErrorCode:
    # `RateLimitError` is a subclass of `APIStatusError`, so it must be
    # checked first. `asyncio.CancelledError` inherits from `BaseException`,
    # which is why this signature is wider than `Exception`.
    if isinstance(exc, anthropic.RateLimitError):
        return ErrorCode.MODEL_RATE_LIMIT
    if isinstance(exc, anthropic.APIStatusError):
        return ErrorCode.MODEL_OVERLOADED
    if isinstance(exc, asyncio.CancelledError):
        return ErrorCode.CANCELLED
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorCode.TOOL_TIMEOUT
    if isinstance(exc, pydantic.ValidationError):
        return ErrorCode.VALIDATION_ERROR
    return ErrorCode.INTERNAL_ERROR
