import time
from typing import Any

import httpx
import structlog

from app.config import settings
from app.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


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

    async def _get_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        response = await self._client.post(
            f"{self._auth_url}/v1/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

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
        """GET /v1/accounts/{account_id} — retrieve account details and status."""
        return await self._request("GET", f"/v1/accounts/{account_id}")

    async def update_account(
        self, account_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /v1/accounts/{account_id} — update account (e.g. assign APR tier)."""
        return await self._request("PATCH", f"/v1/accounts/{account_id}", json=payload)

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make an authenticated request to the Alpaca Broker API."""
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=await self._headers(),
                json=json,
            )
        except httpx.HTTPError as exc:
            logger.error("alpaca_connection_failed", error=str(exc), path=path)
            raise AlpacaBrokerUnavailableError(str(exc)) from exc
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
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

        if response.status_code == 404:
            raise NotFoundError(
                f"Alpaca resource not found: {message}",
                resource="alpaca_account",
            )

        raise AlpacaBrokerError(
            status_code=response.status_code,
            message=message,
            detail=body,
        )
