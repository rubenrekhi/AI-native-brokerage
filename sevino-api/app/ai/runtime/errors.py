"""Error codes surfaced on the SSE ``error`` event."""

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
    # Check ``status_code >= 500`` rather than isinstance(InternalServerError):
    # HTTP 529 (Anthropic's overload signal) routes to ``OverloadedError``,
    # a sibling, and would be missed otherwise.
    # ``APIConnectionError`` covers transport timeouts that don't subclass
    # ``asyncio.TimeoutError``. Signature is ``BaseException`` because
    # ``CancelledError`` inherits from it.
    if isinstance(exc, anthropic.RateLimitError):
        return ErrorCode.MODEL_RATE_LIMIT
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
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
