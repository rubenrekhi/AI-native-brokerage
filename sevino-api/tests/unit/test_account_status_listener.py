from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.listeners.account_status import (
    AccountStatusListener,
    _parse_alpaca_timestamp,
)
from app.services.alpaca_broker import AlpacaBrokerService


@pytest.fixture
def broker():
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


@pytest.fixture
def listener(broker):
    return AccountStatusListener(broker)


@pytest.fixture
def session():
    return AsyncMock()


async def test_well_formed_event_calls_service_with_parsed_fields(
    listener, broker, session, monkeypatch
):
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply
    )

    data = {
        "event_id": 12627517,
        "event_ulid": "01HCMKXQYJ3ZBV66Q21KCT1CR1",
        "account_id": "9ab15e44-0000-4000-8000-000000000001",
        "account_number": "",
        "at": "2023-10-13T13:34:28.306290+00:00",
        "status_from": "SUBMITTED",
        "status_to": "APPROVED",
        "kyc_results": None,
    }

    await listener.handle_event(session, "", data)

    apply.assert_awaited_once_with(
        session,
        alpaca_account_id="9ab15e44-0000-4000-8000-000000000001",
        new_status="APPROVED",
        kyc_results=None,
        event_time=datetime(2023, 10, 13, 13, 34, 28, 306290, tzinfo=timezone.utc),
        alpaca=broker,
    )


async def test_broker_is_forwarded_as_alpaca_kwarg(
    listener, broker, session, monkeypatch
):
    """SEV-318: the listener must forward its base-class ``_broker`` field as
    the ``alpaca`` kwarg so the service can PATCH the FDIC sweep tier on
    activation. If ``BaseSSEListener`` ever renames that field, sweep
    enrollment would silently no-op — this test fails first."""
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply
    )

    await listener.handle_event(
        session, "", {"account_id": "abc", "status_to": "ACTIVE"}
    )

    assert apply.await_args.kwargs["alpaca"] is broker


async def test_kyc_results_forwarded(listener, session, monkeypatch):
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply
    )
    data = {
        "account_id": "abc",
        "status_to": "REJECTED",
        "kyc_results": {"reject": ["OFAC watchlist hit"]},
    }

    await listener.handle_event(session, "", data)

    apply.assert_awaited_once()
    assert apply.await_args.kwargs["kyc_results"] == {
        "reject": ["OFAC watchlist hit"]
    }


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"account_id": "abc"},
        {"status_to": "ACTIVE"},
        {"account_id": "", "status_to": "ACTIVE"},
        {"account_id": "abc", "status_to": ""},
        # Non-dict payloads: the base class only ``isinstance``-guards its
        # own ULID extraction, so handle_event must guard its own ``.get``
        # calls or raise AttributeError. Covers list, scalar, and None —
        # all of which must hit the malformed warning path, not the
        # exception arm in the base class.
        None,
        [],
        [{"account_id": "abc", "status_to": "ACTIVE"}],
        "a string payload",
        42,
    ],
    ids=[
        "empty",
        "missing_status",
        "missing_account_id",
        "empty_account_id",
        "empty_status",
        "none",
        "empty_list",
        "list_of_dict",
        "string",
        "int",
    ],
)
async def test_malformed_or_unhandled_event_skips_service_calls(
    listener, session, monkeypatch, data
):
    apply_status = AsyncMock()
    apply_sweep = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply_status
    )
    monkeypatch.setattr(
        "app.listeners.account_status.apply_sweep_status_change", apply_sweep
    )

    # Must NOT raise — log is the only observable effect.
    await listener.handle_event(session, "", data)

    apply_status.assert_not_awaited()
    apply_sweep.assert_not_awaited()


async def test_cash_interest_event_calls_sweep_service(
    listener, session, monkeypatch
):
    apply_status = AsyncMock()
    apply_sweep = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply_status
    )
    monkeypatch.setattr(
        "app.listeners.account_status.apply_sweep_status_change", apply_sweep
    )

    data = {
        "cash_interest": {
            "USD": {
                "apr_tier_name_from": None,
                "apr_tier_name_to": "standard",
                "status_from": "PENDING_CHANGE",
                "status_to": "ACTIVE",
            }
        },
        "account_id": "382dd20d-0000-4000-8000-000000000001",
        "at": "2024-06-11T19:00:00.000000Z",
        "event_ulid": "01J2VQMVJRMXQRPNS3831XFE1Y",
    }

    await listener.handle_event(session, "", data)

    apply_status.assert_not_awaited()
    apply_sweep.assert_awaited_once_with(
        session,
        alpaca_account_id="382dd20d-0000-4000-8000-000000000001",
        new_status="ACTIVE",
        event_time=datetime(2024, 6, 11, 19, 0, 0, tzinfo=timezone.utc),
    )


async def test_cash_interest_inactive_status_forwarded(
    listener, session, monkeypatch
):
    apply_sweep = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", AsyncMock()
    )
    monkeypatch.setattr(
        "app.listeners.account_status.apply_sweep_status_change", apply_sweep
    )

    await listener.handle_event(
        session,
        "",
        {
            "account_id": "abc",
            "cash_interest": {"USD": {"status_to": "INACTIVE"}},
        },
    )

    assert apply_sweep.await_args.kwargs["new_status"] == "INACTIVE"


async def test_account_status_event_does_not_dispatch_sweep(
    listener, session, monkeypatch
):
    """Path 1 short-circuits before Path 2 — a status-change event with no
    cash_interest payload must not touch the sweep service."""
    apply_status = AsyncMock()
    apply_sweep = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply_status
    )
    monkeypatch.setattr(
        "app.listeners.account_status.apply_sweep_status_change", apply_sweep
    )

    await listener.handle_event(
        session, "", {"account_id": "abc", "status_to": "ACTIVE"}
    )

    apply_status.assert_awaited_once()
    apply_sweep.assert_not_awaited()


async def test_cash_interest_event_with_empty_status_to_skipped(
    listener, session, monkeypatch
):
    """Defensive: nested status_to that is empty/None must not dispatch
    to the sweep service — same falsy-string contract as Path 1."""
    apply_sweep = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", AsyncMock()
    )
    monkeypatch.setattr(
        "app.listeners.account_status.apply_sweep_status_change", apply_sweep
    )

    await listener.handle_event(
        session,
        "",
        {"account_id": "abc", "cash_interest": {"USD": {"status_to": ""}}},
    )

    apply_sweep.assert_not_awaited()


async def test_unparseable_at_timestamp_passes_none(
    listener, session, monkeypatch
):
    apply = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.account_status.apply_account_status_change", apply
    )

    await listener.handle_event(
        session,
        "",
        {"account_id": "abc", "status_to": "ACTIVE", "at": "not-a-date"},
    )

    assert apply.await_args.kwargs["event_time"] is None


async def test_base_class_defaults_used_for_resume():
    """Regression guard: Alpaca's account-status endpoint today emits
    event_ulid in the payload and accepts since_ulid on the query string —
    which matches ``BaseSSEListener`` defaults. If someone ever overrides
    these in the subclass, they'd silently break replay on reconnect."""
    assert AccountStatusListener.resume_field == "event_ulid"
    assert AccountStatusListener.resume_param == "since_ulid"


def test_parse_alpaca_timestamp_accepts_trailing_z():
    """Alpaca emits RFC3339 with a trailing ``Z`` (e.g. 2023-10-13T13:34:28.30629Z)
    — ``datetime.fromisoformat`` on Python 3.11+ handles this natively."""
    parsed = _parse_alpaca_timestamp("2023-10-13T13:34:28.306290Z")
    assert parsed == datetime(
        2023, 10, 13, 13, 34, 28, 306290, tzinfo=timezone.utc
    )


def test_parse_alpaca_timestamp_returns_none_on_junk():
    assert _parse_alpaca_timestamp("") is None
    assert _parse_alpaca_timestamp(None) is None
    assert _parse_alpaca_timestamp("not-a-date") is None
    assert _parse_alpaca_timestamp(12345) is None
