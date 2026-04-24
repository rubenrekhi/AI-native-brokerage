"""Unit tests for app.schemas.phone_auth."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.phone_auth import (
    ConfirmVerificationRequest,
    ConfirmVerificationResponse,
    SendVerificationRequest,
    SendVerificationResponse,
)


class TestSendVerificationRequest:
    def test_valid_phone(self):
        req = SendVerificationRequest(phone_number="+15551234567")
        assert req.phone_number == "+15551234567"

    @pytest.mark.parametrize(
        "bad",
        [
            "5551234567",      # missing country code
            "+25551234567",    # wrong country code
            "+1555123456",     # only 9 digits
            "+155512345678",   # 11 digits
            "+1 555 123 4567", # spaces
            "+1-555-123-4567", # dashes
            "",                # empty
        ],
    )
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValidationError):
            SendVerificationRequest(phone_number=bad)

    def test_phone_required(self):
        with pytest.raises(ValidationError):
            SendVerificationRequest()


class TestConfirmVerificationRequest:
    def test_valid(self):
        req = ConfirmVerificationRequest(phone_number="+15551234567", code="123456")
        assert req.phone_number == "+15551234567"
        assert req.code == "123456"

    @pytest.mark.parametrize(
        "bad",
        ["12345", "1234567", "abcdef", "12 345", "", "12345a"],
    )
    def test_rejects_bad_code(self, bad):
        with pytest.raises(ValidationError):
            ConfirmVerificationRequest(phone_number="+15551234567", code=bad)

    def test_rejects_bad_phone(self):
        with pytest.raises(ValidationError):
            ConfirmVerificationRequest(phone_number="5551234567", code="123456")

    def test_both_fields_required(self):
        with pytest.raises(ValidationError):
            ConfirmVerificationRequest(phone_number="+15551234567")
        with pytest.raises(ValidationError):
            ConfirmVerificationRequest(code="123456")


class TestResponses:
    def test_send_default(self):
        resp = SendVerificationResponse()
        assert resp.sent is True

    def test_confirm_shape(self):
        now = datetime.now(timezone.utc)
        resp = ConfirmVerificationResponse(phone_verified_at=now)
        assert resp.verified is True
        assert resp.phone_verified_at == now
