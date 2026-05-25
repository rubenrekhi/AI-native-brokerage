"""Integration tests for POST /v1/plaid/webhooks against real local Postgres.

Uses the real `app.main:app` so the middleware stack is exercised end-to-end
(including the APIKeyMiddleware exemption for this path).
"""

import base64
import hashlib
import json
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.repositories.plaid_item import PlaidItemRepository
from app.routes.plaid_webhooks import get_plaid
from app.services.plaid_webhooks import _reset_jwk_cache
from tests.integration.conftest import TEST_API_KEY, _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

KID = "plaid-test-kid"


def _b64u(n: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(32, "big")).rstrip(b"=").decode()


def _make_keypair() -> tuple[str, dict[str, Any]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub = private_key.public_key().public_numbers()
    return pem, {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64u(pub.x),
        "y": _b64u(pub.y),
        "alg": "ES256",
        "use": "sig",
        "expired_at": None,
    }


def _sign(private_pem: str, body: bytes) -> str:
    return jwt.encode(
        {
            "iat": int(time.time()),
            "request_body_sha256": hashlib.sha256(body).hexdigest(),
        },
        private_pem,
        algorithm="ES256",
        headers={"kid": KID},
    )


@pytest.fixture
def keypair() -> tuple[str, dict[str, Any]]:
    return _make_keypair()


@pytest.fixture(autouse=True)
def reset_cache():
    _reset_jwk_cache()
    yield
    _reset_jwk_cache()


@pytest.fixture
async def client(keypair):
    _, public_jwk = keypair
    plaid_mock = AsyncMock()
    plaid_mock.get_webhook_verification_key.return_value = public_jwk

    app.dependency_overrides[get_plaid] = lambda: plaid_mock

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_plaid, None)


async def _make_item(
    db_session: AsyncSession, user_id: uuid.UUID, **overrides
):
    defaults = dict(
        user_id=user_id,
        plaid_item_id=f"item_{uuid.uuid4().hex[:8]}",
        plaid_access_token_plaintext="access-sandbox-plaintext",
        plaid_account_id="acct_xyz",
        institution_name="First Platypus Bank",
    )
    defaults.update(overrides)
    item = await PlaidItemRepository.create(db_session, **defaults)
    await db_session.flush()
    return item


class TestReauthTriggers:
    @pytest.mark.parametrize(
        ("webhook_code", "error_code"),
        [
            ("ERROR", "ITEM_LOGIN_REQUIRED"),
            ("PENDING_EXPIRATION", None),
            ("PENDING_DISCONNECT", None),
            ("USER_PERMISSION_REVOKED", None),
        ],
    )
    async def test_flips_status_to_requires_reauth(
        self,
        client,
        keypair,
        db_session,
        test_user,
        webhook_code,
        error_code,
    ):
        item = await _make_item(db_session, test_user)
        private_pem, _ = keypair

        payload: dict[str, Any] = {
            "webhook_type": "ITEM",
            "webhook_code": webhook_code,
            "item_id": item.plaid_item_id,
            "environment": "sandbox",
        }
        if error_code is not None:
            payload["error"] = {
                "error_code": error_code,
                "error_type": "ITEM_ERROR",
            }
        body = json.dumps(payload).encode()

        response = await client.post(
            "/v1/plaid/webhooks",
            content=body,
            headers={
                "Plaid-Verification": _sign(private_pem, body),
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        await db_session.refresh(item)
        assert item.status == "requires_reauth"


class TestLoginRepaired:
    async def test_flips_status_back_to_active(
        self, client, keypair, db_session, test_user
    ):
        item = await _make_item(db_session, test_user)
        await PlaidItemRepository.mark_requires_reauth(
            db_session, item.plaid_item_id
        )
        private_pem, _ = keypair

        body = json.dumps(
            {
                "webhook_type": "ITEM",
                "webhook_code": "LOGIN_REPAIRED",
                "item_id": item.plaid_item_id,
            }
        ).encode()

        response = await client.post(
            "/v1/plaid/webhooks",
            content=body,
            headers={"Plaid-Verification": _sign(private_pem, body)},
        )

        assert response.status_code == 200
        await db_session.refresh(item)
        assert item.status == "active"


class TestNoOpBranches:
    @pytest.mark.parametrize(
        "payload_overrides",
        [
            {"webhook_code": "ERROR", "error": {"error_code": "PRODUCT_NOT_READY"}},
            {"webhook_code": "DEFAULT_UPDATE"},
            {"webhook_type": "TRANSFER", "webhook_code": "ERROR"},
        ],
    )
    async def test_unrelated_webhooks_do_not_touch_status(
        self, client, keypair, db_session, test_user, payload_overrides
    ):
        item = await _make_item(db_session, test_user)
        private_pem, _ = keypair

        payload: dict[str, Any] = {
            "webhook_type": "ITEM",
            "webhook_code": "ERROR",
            "item_id": item.plaid_item_id,
        }
        payload.update(payload_overrides)
        body = json.dumps(payload).encode()

        response = await client.post(
            "/v1/plaid/webhooks",
            content=body,
            headers={"Plaid-Verification": _sign(private_pem, body)},
        )

        assert response.status_code == 200
        await db_session.refresh(item)
        assert item.status == "active"

    async def test_unknown_item_id_returns_200_without_db_write(
        self, client, keypair, test_user, db_session
    ):
        private_pem, _ = keypair
        body = json.dumps(
            {
                "webhook_type": "ITEM",
                "webhook_code": "PENDING_EXPIRATION",
                "item_id": "item_does_not_exist",
            }
        ).encode()

        response = await client.post(
            "/v1/plaid/webhooks",
            content=body,
            headers={"Plaid-Verification": _sign(private_pem, body)},
        )

        assert response.status_code == 200


class TestIdempotency:
    async def test_duplicate_delivery_is_safe(
        self, client, keypair, db_session, test_user
    ):
        item = await _make_item(db_session, test_user)
        private_pem, _ = keypair
        body = json.dumps(
            {
                "webhook_type": "ITEM",
                "webhook_code": "PENDING_EXPIRATION",
                "item_id": item.plaid_item_id,
            }
        ).encode()
        headers = {"Plaid-Verification": _sign(private_pem, body)}

        first = await client.post(
            "/v1/plaid/webhooks", content=body, headers=headers
        )
        second = await client.post(
            "/v1/plaid/webhooks", content=body, headers=headers
        )

        assert first.status_code == 200
        assert second.status_code == 200
        await db_session.refresh(item)
        assert item.status == "requires_reauth"


class TestSignatureFailure:
    async def test_invalid_signature_returns_401(self, client, db_session):
        attacker_pem, _ = _make_keypair()
        body = json.dumps(
            {
                "webhook_type": "ITEM",
                "webhook_code": "PENDING_EXPIRATION",
                "item_id": "item_anything",
            }
        ).encode()

        response = await client.post(
            "/v1/plaid/webhooks",
            content=body,
            headers={"Plaid-Verification": _sign(attacker_pem, body)},
        )

        assert response.status_code == 401
        assert response.json()["code"] == "WEBHOOK_INVALID_SIGNATURE"


class TestMiddlewareExemption:
    async def test_webhook_reachable_without_api_key(
        self, keypair, db_session, test_user
    ):
        _, public_jwk = keypair
        plaid_mock = AsyncMock()
        plaid_mock.get_webhook_verification_key.return_value = public_jwk
        app.dependency_overrides[get_plaid] = lambda: plaid_mock

        item = await _make_item(db_session, test_user)
        private_pem, _ = keypair
        body = json.dumps(
            {
                "webhook_type": "ITEM",
                "webhook_code": "PENDING_EXPIRATION",
                "item_id": item.plaid_item_id,
            }
        ).encode()

        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as ac:
                response = await ac.post(
                    "/v1/plaid/webhooks",
                    content=body,
                    headers={"Plaid-Verification": _sign(private_pem, body)},
                )
        finally:
            app.dependency_overrides.pop(get_plaid, None)

        # Middleware would have returned 403 FORBIDDEN if the path were not
        # exempt; 200 here means the request reached the route.
        assert response.status_code == 200
