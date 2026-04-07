from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError, ProgrammingError

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Standard error response helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Custom exception classes
# ---------------------------------------------------------------------------

class AuthenticationError(Exception):
    def __init__(self, message: str = "Not authenticated"):
        self.message = message


class AuthorizationError(Exception):
    def __init__(self, message: str = "Not authorized"):
        self.message = message


class NotFoundError(Exception):
    def __init__(self, message: str = "Resource not found"):
        self.message = message


class ConflictError(Exception):
    def __init__(self, message: str = "Resource already exists"):
        self.message = message


class IncompleteOnboardingError(Exception):
    def __init__(self, message: str = "Onboarding data incomplete", missing_fields: list[str] | None = None):
        self.message = message
        self.missing_fields = missing_fields or []


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

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
    return error_response(404, exc.message, "NOT_FOUND")


async def conflict_error_handler(
    request: Request, exc: ConflictError
) -> JSONResponse:
    return error_response(409, exc.message, "CONFLICT")


async def incomplete_onboarding_error_handler(
    request: Request, exc: IncompleteOnboardingError
) -> JSONResponse:
    return error_response(
        422, exc.message, "INCOMPLETE_ONBOARDING",
        detail={"missing_fields": exc.missing_fields} if exc.missing_fields else None,
    )


# --- SQLAlchemy handlers (registered before generic Exception) ---

async def data_error_handler(
    request: Request, exc: DataError
) -> JSONResponse:
    logger.warning("sqlalchemy_data_error", error=str(exc))
    return error_response(422, "Invalid data provided", "INVALID_DATA")


async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    logger.warning("sqlalchemy_integrity_error", error=str(exc))
    msg = str(exc.orig) if exc.orig else str(exc)
    if "unique" in msg.lower() or "duplicate" in msg.lower():
        return error_response(409, "A record with this value already exists", "DUPLICATE_ENTRY")
    return error_response(409, "Data conflicts with existing records", "CONFLICT")


async def programming_error_handler(
    request: Request, exc: ProgrammingError
) -> JSONResponse:
    logger.error("sqlalchemy_programming_error", error=str(exc))
    return error_response(500, "Internal server error", "INTERNAL_ERROR")


# --- Generic catch-all ---

async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.error("unhandled_exception", error=str(exc), exc_info=True)
    return error_response(500, "Internal server error", "INTERNAL_ERROR")


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(AuthenticationError, authentication_error_handler)
    app.add_exception_handler(AuthorizationError, authorization_error_handler)
    app.add_exception_handler(NotFoundError, not_found_error_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(IncompleteOnboardingError, incomplete_onboarding_error_handler)
    # SQLAlchemy handlers — registered before generic Exception
    app.add_exception_handler(DataError, data_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(ProgrammingError, programming_error_handler)
    # Generic catch-all — must be last
    app.add_exception_handler(Exception, generic_exception_handler)
