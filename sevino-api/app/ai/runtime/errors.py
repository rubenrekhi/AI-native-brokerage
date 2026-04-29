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
    # `InternalServerError` covers all 5xx responses (incl. 529 "overloaded").
    # 4xx responses other than 429 (`BadRequestError`, `AuthenticationError`,
    # etc.) are config or programmer errors — not overload conditions — so
    # they fall through to `INTERNAL_ERROR` rather than being mislabelled
    # `MODEL_OVERLOADED` and burning Phase 2 retry budget.
    # `APIConnectionError` (incl. its `APITimeoutError` subclass) covers
    # transport-level failures: the SDK's own timeouts and network errors
    # don't subclass `asyncio.TimeoutError` or `APIStatusError`, so without
    # this branch they'd silently fall through to `INTERNAL_ERROR` and be
    # treated as un-retryable.
    # `asyncio.CancelledError` inherits from `BaseException`, which is why
    # this signature is wider than `Exception`.
    if isinstance(exc, anthropic.RateLimitError):
        return ErrorCode.MODEL_RATE_LIMIT
    if isinstance(exc, anthropic.InternalServerError):
        return ErrorCode.MODEL_OVERLOADED
    if isinstance(exc, anthropic.APIConnectionError):
        return ErrorCode.MODEL_OVERLOADED
    if isinstance(exc, asyncio.CancelledError):
        return ErrorCode.CANCELLED
    if isinstance(exc, asyncio.TimeoutError):
        return ErrorCode.TOOL_TIMEOUT
    if isinstance(exc, pydantic.ValidationError):
        return ErrorCode.VALIDATION_ERROR
    return ErrorCode.INTERNAL_ERROR
