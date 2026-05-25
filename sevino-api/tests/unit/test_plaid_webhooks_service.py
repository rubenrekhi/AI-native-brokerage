"""Unit tests for the Plaid webhook signature verifier.

Generates a real ES256 keypair locally and signs synthetic JWTs to exercise
each verification branch end-to-end (no Plaid API calls).
"""

import base64
import hashlib
import time
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.services.plaid import PlaidServiceError
from app.services.plaid_webhooks import _reset_jwk_cache, verify_webhook

KID = "test-kid-abc"


def _b64u_uint(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


def _make_keypair() -> tuple[str, dict[str, Any]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = private_key.public_key().public_numbers()
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64u_uint(pub.x),
        "y": _b64u_uint(pub.y),
        "alg": "ES256",
        "use": "sig",
        "expired_at": None,
    }
    return pem, jwk


def _sign(
    *,
    private_pem: str,
    body: bytes,
    iat: int | None = None,
    kid: str | None = KID,
    alg: str = "ES256",
    body_hash_override: str | None = None,
) -> str:
    claims = {
        "iat": iat if iat is not None else int(time.time()),
        "request_body_sha256": body_hash_override
        if body_hash_override is not None
        else hashlib.sha256(body).hexdigest(),
    }
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, private_pem, algorithm=alg, headers=headers)


@pytest.fixture(autouse=True)
def reset_cache():
    _reset_jwk_cache()
    yield
    _reset_jwk_cache()


@pytest.fixture
def keypair() -> tuple[str, dict[str, Any]]:
    return _make_keypair()


@pytest.fixture
def plaid_mock(keypair) -> AsyncMock:
    _, public_jwk = keypair
    svc = AsyncMock()
    svc.get_webhook_verification_key.return_value = public_jwk
    return svc


def _assert_rejected(exc: PlaidServiceError) -> None:
    assert exc.code == "WEBHOOK_INVALID_SIGNATURE"
    assert exc.status_code == 401


class TestHappyPath:
    async def test_valid_webhook_verifies_silently(self, keypair, plaid_mock):
        private_pem, _ = keypair
        body = b'{"webhook_type":"ITEM","webhook_code":"ERROR"}'
        token = _sign(private_pem=private_pem, body=body)

        await verify_webhook(plaid_mock, raw_body=body, signature_header=token)

        plaid_mock.get_webhook_verification_key.assert_awaited_once_with(KID)

    async def test_cache_hit_does_not_refetch(self, keypair, plaid_mock):
        private_pem, _ = keypair
        body = b"{}"

        token1 = _sign(private_pem=private_pem, body=body)
        await verify_webhook(plaid_mock, raw_body=body, signature_header=token1)

        token2 = _sign(private_pem=private_pem, body=body)
        await verify_webhook(plaid_mock, raw_body=body, signature_header=token2)

        plaid_mock.get_webhook_verification_key.assert_awaited_once()


class TestSignatureFailures:
    @pytest.mark.parametrize("header", [None, ""])
    async def test_missing_or_empty_header_rejected(self, plaid_mock, header):
        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header=header
            )
        _assert_rejected(info.value)
        plaid_mock.get_webhook_verification_key.assert_not_awaited()

    async def test_malformed_jwt_rejected(self, plaid_mock):
        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header="not-a-jwt"
            )
        _assert_rejected(info.value)
        plaid_mock.get_webhook_verification_key.assert_not_awaited()

    async def test_wrong_alg_rejected(self, plaid_mock):
        token = jwt.encode(
            {"iat": int(time.time()), "request_body_sha256": "x"},
            "shared-secret-of-at-least-32-bytes-for-hs256",
            algorithm="HS256",
            headers={"kid": KID},
        )

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header=token
            )

        _assert_rejected(info.value)
        plaid_mock.get_webhook_verification_key.assert_not_awaited()

    async def test_missing_kid_rejected(self, keypair, plaid_mock):
        private_pem, _ = keypair
        token = _sign(private_pem=private_pem, body=b"{}", kid=None)

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header=token
            )

        _assert_rejected(info.value)
        plaid_mock.get_webhook_verification_key.assert_not_awaited()

    async def test_signature_from_different_key_rejected(self, plaid_mock):
        attacker_pem, _ = _make_keypair()
        body = b"{}"
        token = _sign(private_pem=attacker_pem, body=body)

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=body, signature_header=token
            )

        _assert_rejected(info.value)


class TestKeyRotation:
    async def test_upstream_jwk_fetch_failure_surfaces_as_signature_error(
        self, keypair, plaid_mock
    ):
        private_pem, _ = keypair
        plaid_mock.get_webhook_verification_key.side_effect = PlaidServiceError(
            code="INVALID_INPUT", message="unknown kid", status_code=400
        )
        token = _sign(private_pem=private_pem, body=b"{}")

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header=token
            )

        _assert_rejected(info.value)

    async def test_expired_jwk_rejected_on_fetch(self, keypair, plaid_mock):
        private_pem, public_jwk = keypair
        public_jwk["expired_at"] = int(time.time()) - 10
        plaid_mock.get_webhook_verification_key.return_value = public_jwk
        token = _sign(private_pem=private_pem, body=b"{}")

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=b"{}", signature_header=token
            )

        _assert_rejected(info.value)

    async def test_jwk_with_future_expiry_still_accepted(
        self, keypair, plaid_mock
    ):
        private_pem, public_jwk = keypair
        public_jwk["expired_at"] = int(time.time()) + 3600
        plaid_mock.get_webhook_verification_key.return_value = public_jwk
        token = _sign(private_pem=private_pem, body=b"{}")

        await verify_webhook(
            plaid_mock, raw_body=b"{}", signature_header=token
        )


class TestReplayProtection:
    async def test_stale_iat_rejected(self, keypair, plaid_mock):
        private_pem, _ = keypair
        body = b"{}"
        six_minutes_ago = int(time.time()) - (6 * 60)
        token = _sign(private_pem=private_pem, body=body, iat=six_minutes_ago)

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=body, signature_header=token
            )

        _assert_rejected(info.value)

    async def test_future_iat_rejected(self, keypair, plaid_mock):
        private_pem, _ = keypair
        body = b"{}"
        six_minutes_ahead = int(time.time()) + (6 * 60)
        token = _sign(private_pem=private_pem, body=body, iat=six_minutes_ahead)

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=body, signature_header=token
            )

        _assert_rejected(info.value)


class TestBodyTampering:
    async def test_body_hash_mismatch_rejected(self, keypair, plaid_mock):
        private_pem, _ = keypair
        signed_body = b'{"webhook_type":"ITEM"}'
        delivered_body = b'{"webhook_type":"TRANSFER"}'
        token = _sign(private_pem=private_pem, body=signed_body)

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=delivered_body, signature_header=token
            )

        _assert_rejected(info.value)

    async def test_empty_body_hash_claim_rejected(self, keypair, plaid_mock):
        private_pem, _ = keypair
        body = b"{}"
        token = _sign(
            private_pem=private_pem, body=body, body_hash_override=""
        )

        with pytest.raises(PlaidServiceError) as info:
            await verify_webhook(
                plaid_mock, raw_body=body, signature_header=token
            )

        _assert_rejected(info.value)
