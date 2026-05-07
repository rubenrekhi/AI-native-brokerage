import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
import structlog

from app.config import settings
from app.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


# Alpaca transfer states that are still in-flight: money hasn't settled yet.
PENDING_TRANSFER_STATUSES = frozenset(
    {"QUEUED", "APPROVAL_PENDING", "PENDING", "SENT_TO_CLEARING"}
)


class AlpacaBrokerError(Exception):
    """Raised when the Alpaca Broker API returns an error."""

    def __init__(self, status_code: int, message: str, detail: dict[str, Any] | None = None):
        self.status_code = status_code
        self.message = message
        self.detail = detail
        super().__init__(message)


class AlpacaBrokerUnavailableError(Exception):
    """Raised when Alpaca is unreachable (network timeout, connection refused, etc.)."""

    def __init__(self, message: str = "Brokerage service unavailable"):
        self.message = message
        super().__init__(message)


async def _stream_response_bytes(response: httpx.Response) -> AsyncIterator[bytes]:
    """Yield body chunks of an already-sent streaming response, guaranteeing close."""
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()


class AlpacaBrokerService:

    def __init__(self) -> None:
        self._client_id = settings.alpaca_api_key
        self._client_secret = settings.alpaca_secret_key
        self._base_url = settings.alpaca_base_url
        self._auth_url = settings.alpaca_auth_url
        self._access_token: str | None = None
        self._token_expires_at: float = 0
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def access_token(self) -> str:
        """Return a valid OAuth2 bearer token, refreshing if expired.

        Public alias of `_get_token` for callers that need to share this
        service's token cache (e.g. `MarketDataService` reusing the same
        OAuth2 client-credentials flow against a different Alpaca host).
        """
        return await self._get_token()

    async def _get_token(self) -> str:
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        try:
            response = await self._client.post(
                f"{self._auth_url}/v1/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            logger.error("alpaca_token_connection_failed", error=str(exc))
            raise AlpacaBrokerUnavailableError(str(exc)) from exc

        if response.status_code != 200:
            logger.error(
                "alpaca_token_exchange_failed",
                status_code=response.status_code,
                body=response.text,
            )
            raise AlpacaBrokerError(
                status_code=response.status_code,
                message="Failed to authenticate with Alpaca",
            )

        body = response.json()
        self._access_token = body["access_token"]
        self._token_expires_at = time.time() + body.get("expires_in", 899)

        logger.info("alpaca_token_refreshed", expires_in=body.get("expires_in"))
        return self._access_token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/accounts — create a new brokerage account with KYC data."""
        return await self._request("POST", "/v1/accounts", json=payload)

    async def get_account(self, account_id: str) -> dict[str, Any]:
        """GET /v1/accounts/{account_id} — KYC/status metadata.

        Use this for account lifecycle (status, identity, contact). For live
        financial position (equity, cash, buying power), use
        `get_trading_account`.
        """
        return await self._request("GET", f"/v1/accounts/{account_id}")

    async def update_account(
        self, account_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /v1/accounts/{account_id} — update account (e.g. assign APR tier)."""
        return await self._request("PATCH", f"/v1/accounts/{account_id}", json=payload)

    async def get_trading_account(self, account_id: str) -> dict[str, Any]:
        """GET /v1/trading/accounts/{account_id}/account — live equity/cash/buying power.

        Use this for live financial position. For KYC/status metadata, use
        `get_account`.
        """
        return await self._request(
            "GET", f"/v1/trading/accounts/{account_id}/account"
        )

    async def close_account(self, account_id: str) -> dict[str, Any]:
        """POST /v1/accounts/{account_id}/actions/close — initiate account closure."""
        return await self._request(
            "POST", f"/v1/accounts/{account_id}/actions/close"
        )

    async def list_positions(self, account_id: str) -> list[dict[str, Any]]:
        """GET /v1/trading/accounts/{account_id}/positions — open positions."""
        return await self._request(
            "GET", f"/v1/trading/accounts/{account_id}/positions"
        )

    async def get_position(self, account_id: str, symbol: str) -> dict[str, Any]:
        """GET /v1/trading/accounts/{account_id}/positions/{symbol} — single position."""
        return await self._request(
            "GET", f"/v1/trading/accounts/{account_id}/positions/{symbol}"
        )

    async def list_orders(
        self,
        account_id: str,
        *,
        status: Literal["open", "closed", "all"] | None = None,
        side: Literal["buy", "sell"] | None = None,
        symbols: str | None = None,
        after: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        direction: Literal["asc", "desc"] | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/trading/accounts/{account_id}/orders — order history."""
        params = {
            k: v
            for k, v in {
                "status": status,
                "side": side,
                "symbols": symbols,
                "after": after,
                "until": until,
                "limit": limit,
                "direction": direction,
            }.items()
            if v is not None
        }
        return await self._request(
            "GET",
            f"/v1/trading/accounts/{account_id}/orders",
            params=params or None,
        )

    async def create_order(
        self, account_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /v1/trading/accounts/{account_id}/orders — submit a new order."""
        return await self._request(
            "POST",
            f"/v1/trading/accounts/{account_id}/orders",
            json=payload,
        )

    async def get_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        """GET /v1/trading/accounts/{account_id}/orders/{order_id} — single order."""
        return await self._request(
            "GET", f"/v1/trading/accounts/{account_id}/orders/{order_id}"
        )

    async def cancel_order(self, account_id: str, order_id: str) -> None:
        """DELETE /v1/trading/accounts/{account_id}/orders/{order_id}. 204 → None."""
        await self._request(
            "DELETE",
            f"/v1/trading/accounts/{account_id}/orders/{order_id}",
        )

    async def create_ach_relationship(
        self, account_id: str, *, processor_token: str
    ) -> dict[str, Any]:
        """POST /v1/accounts/{id}/ach_relationships — Plaid processor path."""
        return await self._request(
            "POST",
            f"/v1/accounts/{account_id}/ach_relationships",
            json={"processor_token": processor_token},
        )

    async def list_ach_relationships(self, account_id: str) -> list[dict[str, Any]]:
        """GET /v1/accounts/{id}/ach_relationships."""
        return await self._request(
            "GET", f"/v1/accounts/{account_id}/ach_relationships"
        )

    async def delete_ach_relationship(
        self, account_id: str, relationship_id: str
    ) -> None:
        """DELETE /v1/accounts/{id}/ach_relationships/{rel_id}. 204 → None."""
        await self._request(
            "DELETE",
            f"/v1/accounts/{account_id}/ach_relationships/{relationship_id}",
        )

    async def create_transfer(
        self,
        account_id: str,
        *,
        relationship_id: str,
        amount: str,
        direction: str,
    ) -> dict[str, Any]:
        """POST /v1/accounts/{id}/transfers — always ACH, immediate timing."""
        return await self._request(
            "POST",
            f"/v1/accounts/{account_id}/transfers",
            json={
                "transfer_type": "ach",
                "timing": "immediate",
                "relationship_id": relationship_id,
                "amount": amount,
                "direction": direction,
            },
        )

    async def list_transfers(
        self,
        account_id: str,
        *,
        direction: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/accounts/{id}/transfers. Pagination pass-through to Alpaca."""
        params: dict[str, Any] = {}
        if direction is not None:
            params["direction"] = direction
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return await self._request(
            "GET",
            f"/v1/accounts/{account_id}/transfers",
            params=params or None,
        )

    async def list_documents(
        self,
        account_id: str,
        *,
        document_type: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/accounts/{account_id}/documents — statements, 1099s, etc."""
        params = {
            k: v
            for k, v in {"type": document_type, "start": start, "end": end}.items()
            if v
        }
        return await self._request(
            "GET",
            f"/v1/accounts/{account_id}/documents",
            params=params or None,
        )

    async def stream_document(
        self, account_id: str, document_id: str
    ) -> AsyncIterator[bytes]:
        """GET /v1/accounts/{account_id}/documents/{document_id}/download — yields PDF chunks.

        Alpaca 301s to an S3 URL; redirects are followed transparently. The
        response body is streamed rather than buffered so multi-MB tax
        packets don't pin per-request memory on the dyno.

        The upstream request is sent eagerly so a non-2xx status (e.g.
        404 for an unknown document) raises before the caller begins
        iterating — otherwise FastAPI would have already flushed 200
        headers by the time the error surfaced.
        """
        path = f"/v1/accounts/{account_id}/documents/{document_id}/download"
        request = self._client.build_request(
            "GET",
            f"{self._base_url}{path}",
            headers=await self._headers(),
        )
        try:
            response = await self._client.send(
                request, stream=True, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            logger.error("alpaca_connection_failed", error=str(exc), path=path)
            raise AlpacaBrokerUnavailableError(str(exc)) from exc

        if response.status_code not in (200, 201):
            try:
                await response.aread()
                self._handle_response(response)  # always raises
            finally:
                await response.aclose()
        return _stream_response_bytes(response)

    async def list_assets(
        self,
        *,
        status: Literal["active", "inactive"] = "active",
        asset_class: Literal["us_equity", "crypto", "us_option"] = "us_equity",
    ) -> list[dict[str, Any]]:
        """GET /v1/assets — returns the full asset universe for the given filters."""
        return await self._request(
            "GET",
            "/v1/assets",
            params={"status": status, "asset_class": asset_class},
        )

    async def get_apr_tiers(self) -> dict[str, Any]:
        """GET /v1/cash_interest/apr_tiers — list configured APR tiers.

        Not account-scoped: a 404 here means endpoint/tenant misconfiguration,
        not a missing account, so we opt out of the default `NotFoundError`
        mapping and surface the upstream status as `AlpacaBrokerError`.
        """
        return await self._request(
            "GET", "/v1/cash_interest/apr_tiers", not_found_resource=None
        )

    async def get_eod_cash_interest(
        self,
        *,
        account_id: str,
        after: str | None = None,
        before: str | None = None,
        date: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /v1/reporting/eod/cash_interest — daily accrual records.

        `date` is mutually exclusive with `after`/`before` per the upstream
        contract; passing both raises `ValueError` to fail fast at the call
        site rather than silently dropping the range params.

        Alpaca wraps the records in `{"interest": [...], "next_page_token": ...}`;
        we unwrap to the records list since callers iterate them. Pagination is
        not yet exposed — one page (default 1000) covers a full month.
        """
        if date is not None and (after is not None or before is not None):
            raise ValueError(
                "`date` is mutually exclusive with `after`/`before`"
            )
        params: dict[str, str] = {"account_id": account_id}
        if date is not None:
            params["date"] = date
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        response = await self._request(
            "GET", "/v1/reporting/eod/cash_interest", params=params
        )
        return response.get("interest", [])

    async def get_interest_activities(
        self, *, account_id: str
    ) -> list[dict[str, Any]]:
        """GET /v1/accounts/activities/INT — interest activity history.

        Returns all INT activities (SWP sweep interest, MGN margin interest,
        etc.). Filtering by `activity_sub_type` is the caller's responsibility.
        """
        return await self._request(
            "GET",
            "/v1/accounts/activities/INT",
            params={"account_id": account_id},
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        *,
        not_found_resource: str | None = "alpaca_account",
    ) -> Any:
        response = await self._execute(method, path, json=json, params=params)
        return self._handle_response(
            response, not_found_resource=not_found_resource
        )

    async def _execute(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Execute the HTTP request, mapping transport errors to AlpacaBrokerUnavailableError."""
        try:
            return await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=await self._headers(),
                json=json,
                params=params,
            )
        except httpx.HTTPError as exc:
            logger.error("alpaca_connection_failed", error=str(exc), path=path)
            raise AlpacaBrokerUnavailableError(str(exc)) from exc

    def _handle_response(
        self,
        response: httpx.Response,
        *,
        not_found_resource: str | None = "alpaca_account",
    ) -> Any:
        if response.status_code == 204:
            return {}
        if response.status_code in (200, 201):
            return response.json()

        try:
            body = response.json()
        except Exception:
            body = {"message": response.text}

        message = body.get("message", str(body))

        logger.warning(
            "alpaca_api_error",
            status_code=response.status_code,
            message=message,
            url=str(response.url),
        )

        if response.status_code == 404 and not_found_resource is not None:
            raise NotFoundError(
                f"Alpaca resource not found: {message}",
                resource=not_found_resource,
            )

        raise AlpacaBrokerError(
            status_code=response.status_code,
            message=message,
            detail=body,
        )
