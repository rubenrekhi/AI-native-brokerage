"""Tests for the Sentry before_send normalizer (SEV-431)."""

import copy

from app.sentry_config import before_send


# --- helpers ---

def _exc_event(value: str) -> dict:
    """Minimal Sentry event with one exception frame."""
    return {
        "exception": {
            "values": [{"type": "DuplicatePreparedStatementError", "value": value}],
        },
    }


def _log_event(message: str, formatted: str | None = None) -> dict:
    """Minimal Sentry event from LoggingIntegration."""
    entry: dict = {"message": message}
    if formatted is not None:
        entry["formatted"] = formatted
    return {"logentry": entry}


# --- exception path ---

def test_normalizes_numeric_stmt_in_exception():
    event = _exc_event('prepared statement "__asyncpg_stmt_14__" already exists')
    result = before_send(event, {})
    assert result["exception"]["values"][0]["value"] == (
        'prepared statement "__asyncpg_stmt_X__" already exists'
    )


def test_normalizes_hex_stmt_in_exception():
    event = _exc_event('prepared statement "__asyncpg_stmt_b__" already exists')
    result = before_send(event, {})
    assert result["exception"]["values"][0]["value"] == (
        'prepared statement "__asyncpg_stmt_X__" already exists'
    )


def test_normalizes_alphanumeric_stmt_in_exception():
    event = _exc_event('prepared statement "__asyncpg_stmt_a1f__" does not exist')
    result = before_send(event, {})
    assert result["exception"]["values"][0]["value"] == (
        'prepared statement "__asyncpg_stmt_X__" does not exist'
    )


def test_multiple_exception_values():
    event = {
        "exception": {
            "values": [
                {"type": "SomeError", "value": "unrelated error"},
                {
                    "type": "DuplicatePreparedStatementError",
                    "value": 'prepared statement "__asyncpg_stmt_42__" already exists',
                },
            ],
        },
    }
    result = before_send(event, {})
    assert result["exception"]["values"][0]["value"] == "unrelated error"
    assert result["exception"]["values"][1]["value"] == (
        'prepared statement "__asyncpg_stmt_X__" already exists'
    )


# --- logentry path ---

def test_normalizes_logentry_message():
    event = _log_event(
        'sqlalchemy_programming_error error=prepared statement "__asyncpg_stmt_14__" already exists'
    )
    result = before_send(event, {})
    assert "__asyncpg_stmt_X__" in result["logentry"]["message"]
    assert "__asyncpg_stmt_14__" not in result["logentry"]["message"]


def test_normalizes_logentry_formatted():
    event = _log_event(
        "stable message",
        formatted='... "__asyncpg_stmt_c__" already exists ...',
    )
    result = before_send(event, {})
    assert result["logentry"]["message"] == "stable message"
    assert "__asyncpg_stmt_X__" in result["logentry"]["formatted"]


# --- passthrough / no-op ---

def test_unrelated_event_passes_through():
    event = _exc_event("division by zero")
    original = copy.deepcopy(event)
    result = before_send(event, {})
    assert result == original


def test_event_without_exception_or_logentry():
    event = {"message": "plain capture_message text"}
    original = copy.deepcopy(event)
    result = before_send(event, {})
    assert result == original


def test_empty_exception_values():
    event = {"exception": {"values": []}}
    result = before_send(event, {})
    assert result is not None


def test_always_returns_event():
    """before_send must never return None (that would drop the event)."""
    for event in [
        _exc_event('prepared statement "__asyncpg_stmt_1__" already exists'),
        _log_event("something __asyncpg_stmt_ff__"),
        {"message": "hello"},
        {},
    ]:
        assert before_send(event, {}) is not None
