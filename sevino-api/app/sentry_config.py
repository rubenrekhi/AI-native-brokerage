"""Shared Sentry configuration for API and worker processes."""

import re
from typing import Any

# Compiled once at import time — used on every event.
_ASYNCPG_STMT_RE = re.compile(r"__asyncpg_stmt_\w+__")
_ASYNCPG_STMT_REPLACEMENT = "__asyncpg_stmt_X__"


def _normalize_asyncpg_messages(event: dict[str, Any]) -> None:
    """Replace varying ``__asyncpg_stmt_<id>__`` tokens with a fixed placeholder.

    Mutates *event* in place.  Handles both capture paths:

    * ``event["exception"]["values"][*]["value"]`` — real exception captures
    * ``event["logentry"]["message"]`` / ``["formatted"]`` — LoggingIntegration
    """
    # Exception path
    exc_info = event.get("exception")
    if exc_info:
        for frame in exc_info.get("values") or []:
            value = frame.get("value")
            if value and _ASYNCPG_STMT_RE.search(value):
                frame["value"] = _ASYNCPG_STMT_RE.sub(
                    _ASYNCPG_STMT_REPLACEMENT, value
                )

    # Logging path (LoggingIntegration)
    logentry = event.get("logentry")
    if logentry:
        for key in ("message", "formatted"):
            text = logentry.get(key)
            if text and _ASYNCPG_STMT_RE.search(text):
                logentry[key] = _ASYNCPG_STMT_RE.sub(
                    _ASYNCPG_STMT_REPLACEMENT, text
                )


def before_send(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any]:
    """Sentry ``before_send`` hook shared by API and worker.

    Currently normalizes asyncpg prepared-statement identifiers so all
    variants collapse into a single Sentry issue instead of N separate
    ones (SEV-431).
    """
    _normalize_asyncpg_messages(event)
    return event
