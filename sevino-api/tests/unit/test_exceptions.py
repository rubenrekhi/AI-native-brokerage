from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

from app.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    _extract_column,
    alpaca_error_handler,
    alpaca_unavailable_handler,
    authentication_error_handler,
    authorization_error_handler,
    conflict_error_handler,
    data_error_handler,
    generic_exception_handler,
    http_exception_handler,
    integrity_error_handler,
    not_found_error_handler,
    programming_error_handler,
    validation_error_handler,
)
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerUnavailableError

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
    assert "detail" not in body


async def test_not_found_error_includes_resource_in_detail():
    resp = await not_found_error_handler(
        request, NotFoundError("User profile not found", resource="user_profile")
    )
    body = _body(resp)

    assert resp.status_code == 404
    assert body["detail"] == {"resource": "user_profile"}


async def test_conflict_error_includes_resource_in_detail():
    resp = await conflict_error_handler(
        request,
        ConflictError(
            "Brokerage account already exists", resource="brokerage_account"
        ),
    )
    body = _body(resp)

    assert resp.status_code == 409
    assert body["code"] == "CONFLICT"
    assert body["detail"] == {"resource": "brokerage_account"}


async def test_conflict_error_without_detail_omits_it():
    resp = await conflict_error_handler(request, ConflictError())
    body = _body(resp)

    assert resp.status_code == 409
    assert "detail" not in body


# ---------------------------------------------------------------------------
# SQLAlchemy exceptions
# ---------------------------------------------------------------------------

class _FakePgError(Exception):
    """Stand-in for an asyncpg PostgresError with the attributes our handler reads."""

    def __init__(
        self,
        message: str = "",
        *,
        column_name: str | None = None,
        constraint_name: str | None = None,
        table_name: str | None = None,
        detail: str | None = None,
    ):
        super().__init__(message)
        self.column_name = column_name
        self.constraint_name = constraint_name
        self.table_name = table_name
        self.detail = detail


def _make_sa_exc(cls, message="some db error", orig: Exception | None = None):
    """Build a SQLAlchemy exception with an .orig attribute."""
    if orig is None:
        orig = Exception(message)
    return cls("statement", {}, orig)


async def test_data_error_returns_422():
    exc = _make_sa_exc(DataError)
    resp = await data_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 422
    assert body["code"] == "INVALID_DATA"
    assert "detail" not in body


async def test_data_error_includes_field_when_available():
    orig = _FakePgError("invalid input syntax", column_name="age")
    exc = _make_sa_exc(DataError, "invalid input syntax", orig=orig)
    resp = await data_error_handler(request, exc)
    body = _body(resp)

    assert body["detail"] == {"field": "age"}


async def test_integrity_error_unique_returns_duplicate_entry():
    exc = _make_sa_exc(IntegrityError, "unique constraint violated")
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 409
    assert body["code"] == "DUPLICATE_ENTRY"


async def test_integrity_error_unique_extracts_field_from_detail():
    orig = _FakePgError(
        "duplicate key value violates unique constraint",
        detail="Key (email)=(x@y.com) already exists.",
    )
    exc = _make_sa_exc(
        IntegrityError, "duplicate key value violates unique constraint", orig=orig
    )
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert body["code"] == "DUPLICATE_ENTRY"
    assert body["detail"] == {"field": "email"}


async def test_integrity_error_unique_extracts_field_from_constraint_name():
    orig = _FakePgError(
        "duplicate key value violates unique constraint",
        constraint_name="brokerage_accounts_alpaca_account_id_key",
        table_name="brokerage_accounts",
    )
    exc = _make_sa_exc(
        IntegrityError, "duplicate key value violates unique constraint", orig=orig
    )
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert body["detail"] == {"field": "alpaca_account_id"}


async def test_integrity_error_other_returns_conflict():
    exc = _make_sa_exc(IntegrityError, "foreign key constraint violated")
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 409
    assert body["code"] == "CONFLICT"
    assert "detail" not in body


async def test_integrity_error_fk_includes_field():
    orig = _FakePgError(
        "insert or update on table violates foreign key constraint",
        column_name="user_id",
    )
    exc = _make_sa_exc(
        IntegrityError,
        "insert or update on table violates foreign key constraint",
        orig=orig,
    )
    resp = await integrity_error_handler(request, exc)
    body = _body(resp)

    assert body["code"] == "CONFLICT"
    assert body["detail"] == {"field": "user_id"}


# ---------------------------------------------------------------------------
# _extract_column helper
# ---------------------------------------------------------------------------


def test_extract_column_prefers_column_name():
    exc = _make_sa_exc(
        IntegrityError, orig=_FakePgError(column_name="email", constraint_name="xyz")
    )
    assert _extract_column(exc) == "email"


def test_extract_column_parses_composite_key_detail():
    exc = _make_sa_exc(
        IntegrityError,
        orig=_FakePgError(detail="Key (user_id, token)=(1, abc) already exists."),
    )
    assert _extract_column(exc) == "user_id"


def test_extract_column_returns_none_without_orig():
    exc = _make_sa_exc(IntegrityError, orig=Exception("plain"))
    assert _extract_column(exc) is None


def test_extract_column_returns_none_for_pkey_constraint():
    orig = _FakePgError(
        "duplicate key value violates unique constraint",
        constraint_name="brokerage_accounts_pkey",
        table_name="brokerage_accounts",
    )
    exc = _make_sa_exc(
        IntegrityError, "duplicate key value violates unique constraint", orig=orig
    )
    assert _extract_column(exc) is None


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
# Alpaca error handler — surfaces upstream message verbatim, no hardcoded prefix
# ---------------------------------------------------------------------------

async def test_alpaca_error_handler_returns_422_with_code_and_message():
    exc = AlpacaBrokerError(
        status_code=422,
        message="transfer amount must be less than or equal to withdrawable cash",
        detail={"code": 40310000, "message": "transfer amount must be less than or equal to withdrawable cash"},
    )
    resp = await alpaca_error_handler(request, exc)
    body = _body(resp)

    assert resp.status_code == 422
    assert body["code"] == "ALPACA_ERROR"
    assert body["error"] == "transfer amount must be less than or equal to withdrawable cash"
    assert body["detail"] == exc.detail


async def test_alpaca_error_handler_does_not_prefix_non_kyc_messages():
    # Regression guard: the handler previously prefixed every message with
    # "KYC submission failed:", which rendered as nonsense on transfer and
    # bank-link errors. The handler must surface `exc.message` verbatim.
    exc = AlpacaBrokerError(
        status_code=422, message="account is closed"
    )
    body = _body(await alpaca_error_handler(request, exc))

    assert body["error"] == "account is closed"
    assert "KYC" not in body["error"]


async def test_alpaca_error_handler_maps_upstream_5xx_to_502():
    # Upstream 5xx is not a validation error — it's a broker outage masquerading
    # as one. Surface as 502 so clients can distinguish it from user-fixable 4xx.
    exc = AlpacaBrokerError(status_code=500, message="internal alpaca error")
    resp = await alpaca_error_handler(request, exc)

    assert resp.status_code == 502
    assert _body(resp)["code"] == "ALPACA_ERROR"


async def test_alpaca_unavailable_handler_includes_retry_after_header():
    # Per RFC 9110, 503 responses should hint at when to retry. Without this
    # header, well-behaved clients (and CDNs) have no signal to back off.
    resp = await alpaca_unavailable_handler(request, AlpacaBrokerUnavailableError())

    assert resp.status_code == 503
    assert resp.headers.get("retry-after") == "30"


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
