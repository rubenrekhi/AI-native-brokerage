import asyncio

import anthropic
import httpx
import pydantic
import pytest

from app.ai.runtime.errors import ErrorCode, to_error_code


def _http_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )


def test_error_code_has_ten_values():
    assert len(list(ErrorCode)) == 10
    assert {code.value for code in ErrorCode} == {
        "tool_timeout",
        "tool_error",
        "model_overloaded",
        "model_rate_limit",
        "internal_error",
        "cancelled",
        "turn_iteration_limit",
        "tool_call_limit",
        "output_token_limit",
        "validation_error",
    }


def test_rate_limit_error_maps_to_model_rate_limit():
    exc = anthropic.RateLimitError(
        "rate limited", response=_http_response(429), body=None
    )
    assert to_error_code(exc) == ErrorCode.MODEL_RATE_LIMIT


def _http_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def test_internal_server_error_maps_to_model_overloaded():
    # 5xx responses — including 529 "overloaded" — surface as
    # `InternalServerError` in the SDK and indicate transient model-side
    # failures that retry logic should treat as overload.
    exc = anthropic.InternalServerError(
        "server error", response=_http_response(500), body=None
    )
    assert to_error_code(exc) == ErrorCode.MODEL_OVERLOADED


def test_api_timeout_error_maps_to_model_overloaded():
    # `APITimeoutError` does NOT inherit from `asyncio.TimeoutError`; its
    # MRO is APITimeoutError → APIConnectionError → APIError → Exception.
    # Without an explicit branch it would land on INTERNAL_ERROR and not
    # be retried — but a SDK timeout is the canonical transient failure.
    exc = anthropic.APITimeoutError(request=_http_request())
    assert to_error_code(exc) == ErrorCode.MODEL_OVERLOADED


def test_api_connection_error_maps_to_model_overloaded():
    # `APIConnectionError` covers transport-level failures (DNS, refused,
    # reset). Same retry semantics as overload — bucket them together.
    exc = anthropic.APIConnectionError(request=_http_request())
    assert to_error_code(exc) == ErrorCode.MODEL_OVERLOADED


@pytest.mark.parametrize(
    "exc_cls,status",
    [
        (anthropic.BadRequestError, 400),
        (anthropic.AuthenticationError, 401),
        (anthropic.PermissionDeniedError, 403),
        (anthropic.NotFoundError, 404),
        (anthropic.UnprocessableEntityError, 422),
    ],
)
def test_4xx_api_status_errors_map_to_internal_error(exc_cls, status):
    # 4xx errors other than 429 are config/programmer bugs (bad API key,
    # malformed request, etc.) — not overload. They must NOT be labelled
    # MODEL_OVERLOADED, since Phase 2 retry logic would burn budget on
    # requests that can never succeed.
    exc = exc_cls("client error", response=_http_response(status), body=None)
    assert to_error_code(exc) == ErrorCode.INTERNAL_ERROR


def test_cancelled_error_maps_to_cancelled():
    assert to_error_code(asyncio.CancelledError()) == ErrorCode.CANCELLED


def test_timeout_error_maps_to_tool_timeout():
    assert to_error_code(asyncio.TimeoutError()) == ErrorCode.TOOL_TIMEOUT


def test_pydantic_validation_error_maps_to_validation_error():
    class _Model(pydantic.BaseModel):
        x: int

    with pytest.raises(pydantic.ValidationError) as exc_info:
        _Model(x="not an int")  # type: ignore[arg-type]
    assert to_error_code(exc_info.value) == ErrorCode.VALIDATION_ERROR


def test_unknown_exception_maps_to_internal_error():
    assert to_error_code(RuntimeError("boom")) == ErrorCode.INTERNAL_ERROR
    assert to_error_code(ValueError("nope")) == ErrorCode.INTERNAL_ERROR
    assert to_error_code(Exception("generic")) == ErrorCode.INTERNAL_ERROR


def test_rate_limit_checked_before_api_status_error():
    # RateLimitError is a subclass of APIStatusError. The mapping must
    # check the more specific class first so a 429 isn't mislabelled
    # MODEL_OVERLOADED.
    assert issubclass(anthropic.RateLimitError, anthropic.APIStatusError)
    exc = anthropic.RateLimitError(
        "rate limited", response=_http_response(429), body=None
    )
    assert to_error_code(exc) == ErrorCode.MODEL_RATE_LIMIT
