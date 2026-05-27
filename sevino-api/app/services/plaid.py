"""Plaid REST API wrapper — link token mint, public-token exchange, processor token create.

One service method per upstream call. No orchestration here; that lives in
`app/services/funding.py`. Errors bubble up as `PlaidServiceError`; the caller
decides how to map them.

Canonical ref: docs/funding.md.
"""

import asyncio
import json
from typing import Any

import plaid
import structlog
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.processor_token_create_request import ProcessorTokenCreateRequest
from plaid.model.products import Products
from plaid.model.webhook_verification_key_get_request import WebhookVerificationKeyGetRequest

from app.config import settings

logger = structlog.get_logger(__name__)

_ENVIRONMENTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


class PlaidServiceError(Exception):
    """Raised when Plaid returns an error or the request cannot be completed."""

    def __init__(
        self,
        code: str,
        message: str,
        detail: dict[str, Any] | None = None,
        *,
        status_code: int | None = None,
    ):
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


class PlaidService:
    def __init__(self) -> None:
        env_key = settings.plaid_env.strip().lower()
        if env_key not in _ENVIRONMENTS:
            raise ValueError(
                f"Unsupported PLAID_ENV={settings.plaid_env!r}; expected 'sandbox' or 'production'."
            )
        configuration = plaid.Configuration(
            host=_ENVIRONMENTS[env_key],
            api_key={
                "clientId": settings.plaid_client_id,
                "secret": settings.plaid_secret,
            },
        )
        self._api_client = plaid.ApiClient(configuration)
        self._client = plaid_api.PlaidApi(self._api_client)

    def close(self) -> None:
        self._api_client.close()

    async def create_link_token(self, *, user_id: str) -> str:
        """POST /link/token/create — step 1 of the Plaid bank-link flow."""
        request = LinkTokenCreateRequest(
            products=[Products("auth")],
            client_name="Sevino",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            **_webhook_kwargs(),
        )
        response = await self._call(self._client.link_token_create, request)
        return response["link_token"]

    async def exchange_public_token(self, *, public_token: str) -> tuple[str, str]:
        """POST /item/public_token/exchange — step 3 of the Plaid bank-link flow."""
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = await self._call(self._client.item_public_token_exchange, request)
        return response["access_token"], response["item_id"]

    async def create_processor_token(
        self, *, access_token: str, account_id: str
    ) -> str:
        """POST /processor/token/create with `processor=alpaca` — step 4 of the bank-link flow."""
        request = ProcessorTokenCreateRequest(
            access_token=access_token,
            account_id=account_id,
            processor="alpaca",
        )
        response = await self._call(self._client.processor_token_create, request)
        return response["processor_token"]

    async def create_update_link_token(
        self, *, user_id: str, access_token: str
    ) -> str:
        """POST /link/token/create in update mode for an existing item.

        Per Plaid docs, `products` must be omitted in update mode; the
        existing `access_token` remains valid after a successful re-auth,
        so callers do not need to exchange a new public token.
        """
        request = LinkTokenCreateRequest(
            client_name="Sevino",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            access_token=access_token,
            **_webhook_kwargs(),
        )
        response = await self._call(self._client.link_token_create, request)
        return response["link_token"]

    async def get_webhook_verification_key(self, key_id: str) -> dict[str, Any]:
        """POST /webhook_verification_key/get — fetch the JWK for a `kid`."""
        request = WebhookVerificationKeyGetRequest(key_id=key_id)
        response = await self._call(
            self._client.webhook_verification_key_get, request
        )
        return response["key"]

    async def _call(self, fn, request) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(fn, request)
        except plaid.ApiException as exc:
            raise _map_plaid_exception(exc) from exc
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def _webhook_kwargs() -> dict[str, str]:
    """Conditional `webhook=` for `LinkTokenCreateRequest`. Passing
    `webhook=None` would serialize as `"webhook": null` which Plaid rejects;
    omitting the key entirely keeps any existing Dashboard default in place.
    Item webhooks (ITEM_LOGIN_REQUIRED etc.) only fire if the URL is set
    here at link time — modern Plaid has no Dashboard-level default."""
    if settings.plaid_webhook_url:
        return {"webhook": settings.plaid_webhook_url}
    return {}


def _map_plaid_exception(exc: plaid.ApiException) -> PlaidServiceError:
    code = "PLAID_ERROR"
    message = exc.reason or "Plaid API error"
    detail: dict[str, Any] = {"status_code": exc.status}
    body = exc.body
    if body:
        try:
            parsed = json.loads(body) if isinstance(body, (str, bytes)) else dict(body)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            code = parsed.get("error_code") or code
            message = (
                parsed.get("display_message")
                or parsed.get("error_message")
                or message
            )
            detail.update(
                {k: parsed.get(k) for k in ("error_type", "request_id") if parsed.get(k)}
            )
    return PlaidServiceError(code=code, message=message, detail=detail, status_code=exc.status)
