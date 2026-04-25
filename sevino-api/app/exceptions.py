import re
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

logger = structlog.get_logger(__name__)

# asyncpg embeds the offending column in the error `detail` string, e.g.
#   Key (email)=(x@y.com) already exists.
_PG_DETAIL_KEY_RE = re.compile(r"Key \(([^)]+)\)=")


def error_response(
    status_code: int,
    message: str,
    code: str,
    detail: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"error": message, "code": code}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


class AuthenticationError(Exception):
    def __init__(self, message: str = "Not authenticated"):
        self.message = message


class AuthorizationError(Exception):
    def __init__(self, message: str = "Not authorized"):
        self.message = message


class NotFoundError(Exception):
    def __init__(
        self,
        message: str = "Resource not found",
        *,
        resource: str | None = None,
    ):
        self.message = message
        self.resource = resource


class ConflictError(Exception):
    def __init__(
        self,
        message: str = "Resource already exists",
        *,
        code: str = "CONFLICT",
        detail: dict[str, Any] | None = None,
        resource: str | None = None,
        field: str | None = None,
    ):
        self.message = message
        self.code = code
        self.detail = detail
        self.resource = resource
        self.field = field


class IncompleteOnboardingError(Exception):
    def __init__(self, message: str = "Onboarding data incomplete", missing_fields: list[str] | None = None):
        self.message = message
        self.missing_fields = missing_fields or []


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields = []
    for err in exc.errors():
        fields.append({
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        })
    logger.warning("request_validation_error", path=request.url.path, fields=fields)
    return error_response(422, "Validation error", "VALIDATION_ERROR", {"fields": fields})


async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    return error_response(exc.status_code, str(exc.detail), "HTTP_ERROR")


async def authentication_error_handler(
    request: Request, exc: AuthenticationError
) -> JSONResponse:
    return error_response(401, exc.message, "AUTHENTICATION_ERROR")


async def authorization_error_handler(
    request: Request, exc: AuthorizationError
) -> JSONResponse:
    return error_response(403, exc.message, "AUTHORIZATION_ERROR")


async def not_found_error_handler(
    request: Request, exc: NotFoundError
) -> JSONResponse:
    detail = {"resource": exc.resource} if exc.resource else None
    return error_response(404, exc.message, "NOT_FOUND", detail)


async def conflict_error_handler(
    request: Request, exc: ConflictError
) -> JSONResponse:
    # Prefer explicit `detail` if the caller supplied one (funding pattern:
    # e.g. {"account_status": "SUBMITTED"}). Otherwise derive from
    # resource/field kwargs (onboarding/generic pattern).
    detail = exc.detail
    if detail is None and (exc.resource or exc.field):
        detail = {}
        if exc.resource:
            detail["resource"] = exc.resource
        if exc.field:
            detail["field"] = exc.field
    return error_response(409, exc.message, exc.code, detail=detail)


async def incomplete_onboarding_error_handler(
    request: Request, exc: IncompleteOnboardingError
) -> JSONResponse:
    logger.warning(
        "incomplete_onboarding",
        path=request.url.path,
        message=exc.message,
        missing_fields=exc.missing_fields,
    )
    return error_response(
        422, exc.message, "INCOMPLETE_ONBOARDING",
        detail={"missing_fields": exc.missing_fields} if exc.missing_fields else None,
    )


async def alpaca_error_handler(
    request: Request, exc: "AlpacaBrokerError"
) -> JSONResponse:
    logger.error("alpaca_api_error", status_code=exc.status_code, message=exc.message)
    return error_response(422, exc.message, "ALPACA_ERROR", detail=exc.detail)


async def alpaca_unavailable_handler(
    request: Request, exc: "AlpacaBrokerUnavailableError"
) -> JSONResponse:
    logger.error("alpaca_unavailable", error=exc.message)
    return error_response(503, "Brokerage service unavailable, please try again", "ALPACA_UNAVAILABLE")


async def plaid_service_error_handler(
    request: Request, exc: "PlaidServiceError"
) -> JSONResponse:
    logger.error("plaid_service_error", code=exc.code, message=exc.message)
    return error_response(422, exc.message, exc.code, detail=exc.detail)


async def supabase_admin_error_handler(
    request: Request, exc: "SupabaseAdminError"
) -> JSONResponse:
    logger.error(
        "supabase_admin_error", status_code=exc.status_code, message=exc.message
    )
    return error_response(502, exc.message, "SUPABASE_ADMIN_ERROR", detail=exc.detail)


async def supabase_admin_unavailable_handler(
    request: Request, exc: "SupabaseAdminUnavailableError"
) -> JSONResponse:
    logger.error("supabase_admin_unavailable", error=exc.message)
    return error_response(
        503,
        "Account service unavailable, please try again",
        "SUPABASE_ADMIN_UNAVAILABLE",
    )


async def phone_verification_error_handler(
    request: Request, exc: "PhoneVerificationError"
) -> JSONResponse:
    logger.warning("phone_verification_error", message=exc.message)
    return error_response(
        422, exc.message, "PHONE_VERIFICATION_FAILED", detail=exc.detail
    )


async def phone_number_taken_handler(
    request: Request, exc: "PhoneNumberTakenError"
) -> JSONResponse:
    logger.info("phone_number_taken", message=exc.message)
    return error_response(
        409,
        "This phone number is already in use. Please use a different number.",
        "PHONE_NUMBER_TAKEN",
        detail=exc.detail,
    )


async def phone_verification_unavailable_handler(
    request: Request, exc: "PhoneVerificationUnavailableError"
) -> JSONResponse:
    logger.error("phone_verification_unavailable", error=exc.message)
    return error_response(
        503,
        "Phone verification service unavailable, please try again",
        "PHONE_VERIFICATION_UNAVAILABLE",
    )


def _extract_column(exc: Exception) -> str | None:
    """Extract the offending column name from an asyncpg-wrapped SQLAlchemy error.

    Tries in order:
    1. `exc.orig.column_name` (set for NOT NULL / FK / CHECK violations).
    2. Regex match on `exc.orig.detail` (set for unique-key violations,
       e.g. ``Key (email)=(x@y.com) already exists.``).
    3. Stripping ``<table>_`` prefix and ``_key``/``_fkey``/``_check`` suffix
       from `exc.orig.constraint_name` when the conventional naming is used.

    Never returns raw SQL, table names, or values — only a column identifier.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None

    column = getattr(orig, "column_name", None)
    if column:
        return column

    detail = getattr(orig, "detail", None)
    if detail:
        match = _PG_DETAIL_KEY_RE.search(detail)
        if match:
            # Keys can be composite: "(a, b)". Return the first column only.
            return match.group(1).split(",")[0].strip()

    constraint = getattr(orig, "constraint_name", None)
    table = getattr(orig, "table_name", None)
    if constraint:
        stripped = constraint
        if table and stripped.startswith(f"{table}_"):
            stripped = stripped[len(table) + 1 :]
        suffix_matched = False
        for suffix in ("_key", "_fkey", "_pkey", "_check", "_unique", "_idx"):
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)]
                suffix_matched = True
                break
        if suffix_matched and stripped:
            return stripped

    return None


async def data_error_handler(
    request: Request, exc: DataError
) -> JSONResponse:
    logger.warning("sqlalchemy_data_error", error=str(exc))
    column = _extract_column(exc)
    detail = {"field": column} if column else None
    return error_response(422, "Invalid data provided", "INVALID_DATA", detail)


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    logger.warning("sqlalchemy_integrity_error", error=str(exc))
    msg = str(exc.orig) if exc.orig else str(exc)
    column = _extract_column(exc)
    detail = {"field": column} if column else None
    if "unique" in msg.lower() or "duplicate" in msg.lower():
        return error_response(
            409, "A record with this value already exists", "DUPLICATE_ENTRY", detail
        )
    return error_response(409, "Data conflicts with existing records", "CONFLICT", detail)


async def programming_error_handler(
    request: Request, exc: ProgrammingError
) -> JSONResponse:
    logger.error("sqlalchemy_programming_error", error=str(exc))
    return error_response(500, "Internal server error", "INTERNAL_ERROR")


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return error_response(500, "Internal server error", "INTERNAL_ERROR")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(AuthenticationError, authentication_error_handler)
    app.add_exception_handler(AuthorizationError, authorization_error_handler)
    app.add_exception_handler(NotFoundError, not_found_error_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(IncompleteOnboardingError, incomplete_onboarding_error_handler)
    from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerUnavailableError
    app.add_exception_handler(AlpacaBrokerError, alpaca_error_handler)
    app.add_exception_handler(AlpacaBrokerUnavailableError, alpaca_unavailable_handler)
    from app.services.plaid import PlaidServiceError
    app.add_exception_handler(PlaidServiceError, plaid_service_error_handler)
    from app.services.supabase_admin import (
        SupabaseAdminError,
        SupabaseAdminUnavailableError,
    )
    app.add_exception_handler(SupabaseAdminError, supabase_admin_error_handler)
    app.add_exception_handler(
        SupabaseAdminUnavailableError, supabase_admin_unavailable_handler
    )
    from app.services.phone_verification import (
        PhoneNumberTakenError,
        PhoneVerificationError,
        PhoneVerificationUnavailableError,
    )
    # Both handlers can be registered in any order — Starlette dispatches by
    # walking `type(exc).__mro__`, so the subclass handler always wins for
    # `PhoneNumberTakenError` regardless of insertion order. Listing the
    # subclass first just keeps the dispatch order obvious to readers.
    app.add_exception_handler(PhoneNumberTakenError, phone_number_taken_handler)
    app.add_exception_handler(PhoneVerificationError, phone_verification_error_handler)
    app.add_exception_handler(
        PhoneVerificationUnavailableError, phone_verification_unavailable_handler
    )
    # SQLAlchemy handlers — registered before generic Exception
    app.add_exception_handler(DataError, data_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(ProgrammingError, programming_error_handler)
    # Generic catch-all — must be last
    app.add_exception_handler(Exception, generic_exception_handler)
