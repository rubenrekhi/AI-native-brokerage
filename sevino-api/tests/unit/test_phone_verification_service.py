"""Unit tests for app.services.phone_verification."""

import json

import httpx
import pytest

from app.services.phone_verification import (
    PhoneVerificationError,
    PhoneVerificationService,
    PhoneVerificationUnavailableError,
)

USER_JWT = "user-jwt-xyz"
PHONE = "+15551234567"
TOKEN = "123456"


def _make_service(handler) -> PhoneVerificationService:
    """Build a PhoneVerificationService whose AsyncClient uses MockTransport."""
    service = PhoneVerificationService()
    service._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=10.0
    )
    return service


# ---------------------------------------------------------------------------
# send — happy path
# ---------------------------------------------------------------------------


class TestSend:
    async def test_puts_phone_to_user_endpoint(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"id": "user-abc"})

        service = _make_service(handler)
        result = await service.send(user_jwt=USER_JWT, phone_number=PHONE)

        assert result is None
        assert captured["method"] == "PUT"
        assert captured["url"].endswith("/auth/v1/user")
        assert captured["body"] == {"phone": PHONE}
        assert captured["headers"]["authorization"] == f"Bearer {USER_JWT}"
        assert captured["headers"]["apikey"]
        assert captured["headers"]["content-type"] == "application/json"

    async def test_400_raises_phone_verification_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"msg": "Invalid phone number", "code": "invalid_phone"}
            )

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationError) as info:
            await service.send(user_jwt=USER_JWT, phone_number="+1bogus")

        assert "Invalid phone number" in info.value.message
        assert info.value.detail == {
            "msg": "Invalid phone number",
            "code": "invalid_phone",
        }

    async def test_422_raises_phone_verification_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "validation failed"})

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationError) as info:
            await service.send(user_jwt=USER_JWT, phone_number=PHONE)

        assert "validation failed" in info.value.message

    async def test_429_raises_phone_verification_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429, json={"msg": "For security purposes, please wait 60 seconds"}
            )

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationError) as info:
            await service.send(user_jwt=USER_JWT, phone_number=PHONE)

        assert "60 seconds" in info.value.message

    async def test_500_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"msg": "internal error"})

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationUnavailableError):
            await service.send(user_jwt=USER_JWT, phone_number=PHONE)

    async def test_401_raises_phone_verification_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"msg": "invalid jwt"})

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationError) as info:
            await service.send(user_jwt="expired", phone_number=PHONE)

        assert "invalid jwt" in info.value.message

    async def test_network_failure_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationUnavailableError):
            await service.send(user_jwt=USER_JWT, phone_number=PHONE)


# ---------------------------------------------------------------------------
# confirm — happy path
# ---------------------------------------------------------------------------


class TestConfirm:
    async def test_posts_verify_with_phone_change(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={"access_token": "new-jwt", "user": {"phone": PHONE}},
            )

        service = _make_service(handler)
        result = await service.confirm(
            user_jwt=USER_JWT, phone_number=PHONE, token=TOKEN
        )

        assert captured["method"] == "POST"
        assert captured["url"].endswith("/auth/v1/verify")
        assert captured["body"] == {
            "type": "phone_change",
            "phone": PHONE,
            "token": TOKEN,
        }
        assert captured["headers"]["authorization"] == f"Bearer {USER_JWT}"
        assert captured["headers"]["apikey"]
        assert result["access_token"] == "new-jwt"

    async def test_wrong_otp_raises_phone_verification_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={"msg": "Token has expired or is invalid", "code": "otp_expired"},
            )

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationError) as info:
            await service.confirm(
                user_jwt=USER_JWT, phone_number=PHONE, token="999999"
            )

        assert "Token has expired" in info.value.message
        assert info.value.detail == {
            "msg": "Token has expired or is invalid",
            "code": "otp_expired",
        }

    async def test_500_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"msg": "internal error"})

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationUnavailableError):
            await service.confirm(
                user_jwt=USER_JWT, phone_number=PHONE, token=TOKEN
            )

    async def test_network_failure_raises_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        service = _make_service(handler)
        with pytest.raises(PhoneVerificationUnavailableError):
            await service.confirm(
                user_jwt=USER_JWT, phone_number=PHONE, token=TOKEN
            )


# ---------------------------------------------------------------------------
# _handle_response — edge cases
# ---------------------------------------------------------------------------


class TestHandleResponse:
    def test_204_returns_empty_dict(self):
        service = PhoneVerificationService.__new__(PhoneVerificationService)
        response = httpx.Response(
            status_code=204,
            request=httpx.Request("PUT", "http://localhost/auth/v1/user"),
        )
        assert service._handle_response(response) == {}

    def test_empty_2xx_body_returns_empty_dict(self):
        service = PhoneVerificationService.__new__(PhoneVerificationService)
        response = httpx.Response(
            status_code=200,
            text="",
            request=httpx.Request("PUT", "http://localhost/auth/v1/user"),
        )
        assert service._handle_response(response) == {}

    def test_non_json_body_falls_back_to_text(self):
        service = PhoneVerificationService.__new__(PhoneVerificationService)
        response = httpx.Response(
            status_code=400,
            text="not json",
            request=httpx.Request("PUT", "http://localhost/auth/v1/user"),
        )
        with pytest.raises(PhoneVerificationError) as info:
            service._handle_response(response)

        assert info.value.detail == {"message": "not json"}

    def test_error_description_used_when_msg_and_message_absent(self):
        service = PhoneVerificationService.__new__(PhoneVerificationService)
        response = httpx.Response(
            status_code=400,
            json={"error_description": "Rate limit on sms send"},
            request=httpx.Request("PUT", "http://localhost/auth/v1/user"),
        )
        with pytest.raises(PhoneVerificationError) as info:
            service._handle_response(response)

        assert "Rate limit on sms send" in info.value.message
