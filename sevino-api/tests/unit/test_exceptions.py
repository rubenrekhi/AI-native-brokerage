from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    authentication_error_handler,
    authorization_error_handler,
    data_error_handler,
    generic_exception_handler,
    http_exception_handler,
    integrity_error_handler,
    not_found_error_handler,
    programming_error_handler,
    validation_error_handler,
)

request = MagicMock()


def _body(response):
    """Extract the JSON body dict from a JSONResponse."""
    import json

    return json.loads(response.body.decode())


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

async def test_validation_error_returns_422_with_field_details():
    exc = RequestValidationError(
        errors=[
            {
                "loc": ("body", "email"),
                "msg": "field required",
                "type": "value_error.missing",
            }
        ]
    )
    resp = await validation_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"]["fields"][0]["field"] == "body.email"


# ---------------------------------------------------------------------------
# HTTP exception
# ---------------------------------------------------------------------------

async def test_http_exception_preserves_status_code():
    exc = HTTPException(status_code=429, detail="Too many requests")
    resp = await http_exception_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 429
    assert body["error"] == "Too many requests"
    assert body["code"] == "HTTP_ERROR"


# ---------------------------------------------------------------------------
# Custom app exceptions
# ---------------------------------------------------------------------------

async def test_authentication_error_returns_401():
    resp = await authentication_error_handler(request, AuthenticationError())
    body = _body(resp)

    assert resp.status_code == 401
    assert body["code"] == "AUTHENTICATION_ERROR"


async def test_authentication_error_custom_message():
    resp = await authentication_error_handler(
        request, AuthenticationError("Token expired")
    )
    assert _body(resp)["error"] == "Token expired"


async def test_authorization_error_returns_403():
    resp = await authorization_error_handler(request, AuthorizationError())
    body = _body(resp)

    assert resp.status_code == 403
    assert body["code"] == "AUTHORIZATION_ERROR"


async def test_not_found_error_returns_404():
    resp = await not_found_error_handler(request, NotFoundError("User not found"))
    body = _body(resp)

    assert resp.status_code == 404
    assert body["code"] == "NOT_FOUND"
    assert body["error"] == "User not found"


# ---------------------------------------------------------------------------
# SQLAlchemy exceptions
# ---------------------------------------------------------------------------

def _make_sa_exc(cls, message="some db error"):
    """Build a SQLAlchemy exception with an .orig attribute."""
    orig = Exception(message)
    return cls("statement", {}, orig)


async def test_data_error_returns_422():
    exc = _make_sa_exc(DataError)
    resp = await data_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 422
    assert body["code"] == "INVALID_DATA"


async def test_integrity_error_unique_returns_duplicate_entry():
    exc = _make_sa_exc(IntegrityError, "unique constraint violated")
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 409
    assert body["code"] == "DUPLICATE_ENTRY"


async def test_integrity_error_other_returns_conflict():
    exc = _make_sa_exc(IntegrityError, "foreign key constraint violated")
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 409
    assert body["code"] == "CONFLICT"


async def test_programming_error_returns_500():
    exc = _make_sa_exc(ProgrammingError)
    resp = await programming_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 500
    assert body["code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Generic catch-all
# ---------------------------------------------------------------------------

async def test_generic_exception_returns_500_without_leaking():
    exc = RuntimeError("secret database password in message")
    resp = await generic_exception_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 500
    assert body["error"] == "Internal server error"
    assert body["code"] == "INTERNAL_ERROR"
    assert "secret" not in str(body)


# ---------------------------------------------------------------------------
# Standard error shape — every handler includes error + code keys
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "handler,exc",
    [
        (authentication_error_handler, AuthenticationError()),
        (authorization_error_handler, AuthorizationError()),
        (not_found_error_handler, NotFoundError()),
        (generic_exception_handler, RuntimeError("boom")),
    ],
)
async def test_all_responses_have_error_and_code_keys(handler, exc):
    body = _body(await handler(request, exc))
    assert "error" in body
    assert "code" in body
