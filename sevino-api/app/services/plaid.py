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

from app.config import settings

logger = structlog.get_logger(__name__)

_ENVIRONMENTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


class PlaidServiceError(Exception):
    """Raised when Plaid returns an error or the request cannot be completed."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.detail = detail
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
        """Step 1 — POST /link/token/create. Returns `link_token`."""
        request = LinkTokenCreateRequest(
            products=[Products("auth")],
            client_name="Sevino",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
        )
        response = await self._call(self._client.link_token_create, request)
        return response["link_token"]

    async def exchange_public_token(self, *, public_token: str) -> tuple[str, str]:
        """Step 3 — POST /item/public_token/exchange. Returns `(access_token, item_id)`."""
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = await self._call(self._client.item_public_token_exchange, request)
        return response["access_token"], response["item_id"]

    async def create_processor_token(
        self, *, access_token: str, account_id: str
    ) -> str:
        """Step 4 — POST /processor/token/create with `processor=alpaca`.
        Returns `processor_token`."""
        request = ProcessorTokenCreateRequest(
            access_token=access_token,
            account_id=account_id,
            processor="alpaca",
        )
        response = await self._call(self._client.processor_token_create, request)
        return response["processor_token"]

    async def _call(self, fn, request) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(fn, request)
        except plaid.ApiException as exc:
            raise _map_plaid_exception(exc) from exc
        return result.to_dict() if hasattr(result, "to_dict") else dict(result)


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
    return PlaidServiceError(code=code, message=message, detail=detail)
