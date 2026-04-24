from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class PhoneVerificationError(Exception):
    """Raised when Supabase GoTrue rejects a phone verification request."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class PhoneVerificationUnavailableError(Exception):
    """Raised when GoTrue is unreachable (network timeout, connection refused, etc.)."""

    def __init__(self, message: str = "Phone verification service unavailable"):
        self.message = message
        super().__init__(message)


class PhoneVerificationService:
    """Thin wrapper over Supabase GoTrue's phone-change OTP endpoints.

    `send` triggers an OTP via ``PUT /auth/v1/user`` (GoTrue delegates to the
    configured SMS provider — Twilio Verify in our setup).
    `confirm` submits the OTP via ``POST /auth/v1/verify`` with
    ``type=phone_change``.
    """

    def __init__(self) -> None:
        self._base_url = settings.supabase_url
        self._anon_key = settings.supabase_anon_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, *, user_jwt: str, phone_number: str) -> None:
        """Ask GoTrue to dispatch a phone-change OTP to ``phone_number``."""
        await self._request(
            "PUT",
            "/auth/v1/user",
            user_jwt=user_jwt,
            json={"phone": phone_number},
        )

    async def confirm(
        self, *, user_jwt: str, phone_number: str, token: str
    ) -> dict[str, Any]:
        """Confirm a phone-change OTP. Returns the GoTrue token-refresh body."""
        return await self._request(
            "POST",
            "/auth/v1/verify",
            user_jwt=user_jwt,
            json={"type": "phone_change", "phone": phone_number, "token": token},
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_jwt: str,
        json: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {user_jwt}",
            "apikey": self._anon_key,
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
            )
        except httpx.HTTPError as exc:
            logger.error("gotrue_connection_failed", error=str(exc), path=path)
            raise PhoneVerificationUnavailableError(str(exc)) from exc
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> Any:
        if response.status_code == 204:
            return {}
        if 200 <= response.status_code < 300:
            return response.json()

        try:
            body = response.json()
        except Exception:
            body = {"message": response.text}

        message = (
            body.get("msg")
            or body.get("message")
            or body.get("error_description")
            or str(body)
        )

        logger.warning(
            "gotrue_api_error",
            status_code=response.status_code,
            message=message,
            url=str(response.url),
        )

        if response.status_code >= 500:
            raise PhoneVerificationUnavailableError(message)

        raise PhoneVerificationError(message=message, detail=body)
