import base64
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


class AlpacaBrokerService:

    def __init__(self) -> None:
        credentials = f"{settings.alpaca_api_key}:{settings.alpaca_secret_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
        }
        self._base_url = settings.alpaca_base_url

    async def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/accounts — create a new brokerage account with KYC data."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/v1/accounts",
                headers=self._headers,
                json=payload,
                timeout=30.0,
            )
        return self._handle_response(response)

    async def get_account(self, account_id: str) -> dict[str, Any]:
        """GET /v1/accounts/{account_id} — retrieve account details and status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/v1/accounts/{account_id}",
                headers=self._headers,
                timeout=15.0,
            )
        return self._handle_response(response)

    async def update_account(
        self, account_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH /v1/accounts/{account_id} — update account (e.g. assign APR tier)."""
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self._base_url}/v1/accounts/{account_id}",
                headers=self._headers,
                json=payload,
                timeout=15.0,
            )
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
            raise NotFoundError(f"Alpaca resource not found: {message}")

        raise AlpacaBrokerError(
            status_code=response.status_code,
            message=message,
            detail=body,
        )
