from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.listeners.transfer_status import (
    TransferStatusListener,
    _parse_alpaca_timestamp,
)
from app.services.alpaca_broker import AlpacaBrokerService


@pytest.fixture
def broker():
    return AlpacaBrokerService.__new__(AlpacaBrokerService)


@pytest.fixture
def redis_mock():
    return AsyncMock()


@pytest.fixture
def listener(broker, redis_mock):
    return TransferStatusListener(broker, redis_mock)


@pytest.fixture
def session():
    return AsyncMock()


def test_listener_stream_config(listener):
    # Regression guard on the Alpaca contract — these values determine the
    # endpoint we connect to and the resume parameter on reconnect.
    assert listener.stream_name == "funding_status_sse"
    assert listener.endpoint_path == "/v2/events/funding/status"
    assert listener.resume_field == "event_id"
    assert listener.resume_param == "since_id"
    assert listener.silence_threshold_seconds == 90


async def test_well_formed_transfer_event_delegates_to_service(
    listener, redis_mock, session, monkeypatch
):
    service = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.transfer_status.handle_transfer_status_change", service
    )

    data = {
        "event_id": "01KSNXMX16PS68V9602HM2M0MT",
        "account_id": "bcccad4e-310b-4441-9fc0-907c3b412646",
        "at": "2026-05-27T23:52:19.238476Z",
        "correspondent": "b0sK",
        "entity_id": "d206f438-6275-44e5-86b4-1da2ec53fad0",
        "entity_type": "Transfer",
        "reason": "",
        "status_from": "",
        "status_to": "QUEUED",
    }

    await listener.handle_event(session, "", data)

    service.assert_awaited_once_with(
        session,
        redis_mock,
        alpaca_account_id="bcccad4e-310b-4441-9fc0-907c3b412646",
        transfer_id="d206f438-6275-44e5-86b4-1da2ec53fad0",
        status_from="",
        status_to="QUEUED",
        event_time=datetime(2026, 5, 27, 23, 52, 19, 238476, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "entity_type",
    ["BankRelationship", "WireBank", None, "UnknownNewType"],
)
async def test_non_transfer_entity_skipped(
    listener, session, monkeypatch, entity_type
):
    service = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.transfer_status.handle_transfer_status_change", service
    )

    data = {
        "event_id": "01KSNXMX16PS68V9602HM2M0MT",
        "account_id": "bcccad4e-310b-4441-9fc0-907c3b412646",
        "entity_id": "d206f438-6275-44e5-86b4-1da2ec53fad0",
        "entity_type": entity_type,
        "status_to": "QUEUED",
    }
    if entity_type is None:
        del data["entity_type"]

    await listener.handle_event(session, "", data)

    service.assert_not_awaited()


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        "string",
        42,
        # Missing required field cases
        {"entity_type": "Transfer", "entity_id": "x", "status_to": "QUEUED"},
        {"entity_type": "Transfer", "account_id": "a", "status_to": "QUEUED"},
        {"entity_type": "Transfer", "account_id": "a", "entity_id": "x"},
    ],
)
async def test_malformed_payload_skipped(listener, session, monkeypatch, data):
    service = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.transfer_status.handle_transfer_status_change", service
    )

    await listener.handle_event(session, "", data)

    service.assert_not_awaited()


async def test_empty_status_from_forwarded_as_is(
    listener, redis_mock, session, monkeypatch
):
    # Alpaca emits status_from="" (not None) for first-status events.
    # Confirmed by SEV-594 sandbox capture. Service is responsible for
    # treating "" as "no prior status".
    service = AsyncMock()
    monkeypatch.setattr(
        "app.listeners.transfer_status.handle_transfer_status_change", service
    )

    data = {
        "event_id": "01KSNXMX16PS68V9602HM2M0MT",
        "account_id": "a",
        "entity_id": "x",
        "entity_type": "Transfer",
        "status_from": "",
        "status_to": "QUEUED",
    }

    await listener.handle_event(session, "", data)

    _, kwargs = service.call_args
    assert kwargs["status_from"] == ""


def test_parse_alpaca_timestamp_rfc3339_with_z():
    assert _parse_alpaca_timestamp("2026-05-27T23:52:19.238476Z") == datetime(
        2026, 5, 27, 23, 52, 19, 238476, tzinfo=timezone.utc
    )


@pytest.mark.parametrize("value", ["", "not-a-date", None, 42, []])
def test_parse_alpaca_timestamp_returns_none_for_garbage(value):
    assert _parse_alpaca_timestamp(value) is None
