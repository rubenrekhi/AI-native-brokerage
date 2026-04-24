"""Integration tests for /auth/phone/* endpoints against real local Postgres.

Requires: Docker + `make infra` + `make migrate`.
Skipped automatically if Postgres is unavailable.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.auth import get_access_token
from app.main import app
from app.routes.phone_auth import get_phone_verification
from app.services.phone_verification import (
    PhoneVerificationError,
    PhoneVerificationUnavailableError,
)
from tests.integration.conftest import TEST_USER_ID, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


PHONE = "+15551234567"
CODE = "123456"


@pytest.fixture
def mock_phone_service():
    service = AsyncMock()
    service.send = AsyncMock(return_value=None)
    service.confirm = AsyncMock(return_value={"access_token": "new-jwt"})
    return service


@pytest.fixture(autouse=True)
def override_access_token():
    app.dependency_overrides[get_access_token] = lambda: "fake-user-jwt"
    yield
    app.dependency_overrides.pop(get_access_token, None)


@pytest.fixture
def override_phone_service(mock_phone_service):
    app.dependency_overrides[get_phone_verification] = lambda: mock_phone_service
    yield mock_phone_service
    app.dependency_overrides.pop(get_phone_verification, None)


# ---------------------------------------------------------------------------
# POST /auth/phone/send-verification
# ---------------------------------------------------------------------------


class TestSendVerification:
    async def test_happy_path_calls_service(
        self, authenticated_db_client, override_phone_service
    ):
        response = await authenticated_db_client.post(
            "/auth/phone/send-verification",
            json={"phone_number": PHONE},
        )
        assert response.status_code == 200
        assert response.json() == {"sent": True}
        override_phone_service.send.assert_awaited_once_with(
            user_jwt="fake-user-jwt", phone_number=PHONE
        )

    async def test_invalid_phone_returns_422(
        self, authenticated_db_client, override_phone_service
    ):
        response = await authenticated_db_client.post(
            "/auth/phone/send-verification",
            json={"phone_number": "5551234567"},
        )
        assert response.status_code == 422
        override_phone_service.send.assert_not_called()

    async def test_gotrue_error_returns_422_phone_verification_failed(
        self, authenticated_db_client, override_phone_service
    ):
        override_phone_service.send.side_effect = PhoneVerificationError(
            "Invalid phone number", detail={"code": "invalid_phone"}
        )
        response = await authenticated_db_client.post(
            "/auth/phone/send-verification",
            json={"phone_number": PHONE},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "PHONE_VERIFICATION_FAILED"
        assert body["error"] == "Invalid phone number"

    async def test_gotrue_unavailable_returns_503(
        self, authenticated_db_client, override_phone_service
    ):
        override_phone_service.send.side_effect = PhoneVerificationUnavailableError(
            "connection refused"
        )
        response = await authenticated_db_client.post(
            "/auth/phone/send-verification",
            json={"phone_number": PHONE},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "PHONE_VERIFICATION_UNAVAILABLE"


# ---------------------------------------------------------------------------
# POST /auth/phone/confirm
# ---------------------------------------------------------------------------


class TestConfirmVerification:
    async def test_happy_path_marks_phone_verified(
        self, authenticated_db_client, override_phone_service, db_session
    ):
        response = await authenticated_db_client.post(
            "/auth/phone/confirm",
            json={"phone_number": PHONE, "code": CODE},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["verified"] is True
        assert body["phone_verified_at"]

        override_phone_service.confirm.assert_awaited_once_with(
            user_jwt="fake-user-jwt", phone_number=PHONE, token=CODE
        )

        row = await db_session.execute(
            text(
                "SELECT phone_number, phone_verified_at "
                "FROM user_profiles WHERE id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        result = row.one()
        assert result.phone_number == PHONE
        assert result.phone_verified_at is not None

    async def test_wrong_otp_returns_422_and_does_not_set_verified(
        self, authenticated_db_client, override_phone_service, db_session
    ):
        override_phone_service.confirm.side_effect = PhoneVerificationError(
            "Token has expired or is invalid", detail={"code": "otp_expired"}
        )
        response = await authenticated_db_client.post(
            "/auth/phone/confirm",
            json={"phone_number": PHONE, "code": "999999"},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "PHONE_VERIFICATION_FAILED"

        row = await db_session.execute(
            text(
                "SELECT phone_verified_at FROM user_profiles WHERE id = :id"
            ),
            {"id": uuid.UUID(TEST_USER_ID)},
        )
        assert row.one().phone_verified_at is None

    async def test_invalid_code_format_returns_422(
        self, authenticated_db_client, override_phone_service
    ):
        response = await authenticated_db_client.post(
            "/auth/phone/confirm",
            json={"phone_number": PHONE, "code": "abc"},
        )
        assert response.status_code == 422
        override_phone_service.confirm.assert_not_called()

    async def test_gotrue_unavailable_returns_503(
        self, authenticated_db_client, override_phone_service
    ):
        override_phone_service.confirm.side_effect = PhoneVerificationUnavailableError()
        response = await authenticated_db_client.post(
            "/auth/phone/confirm",
            json={"phone_number": PHONE, "code": CODE},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "PHONE_VERIFICATION_UNAVAILABLE"
