"""Thin wrapper around Supabase GoTrue's privileged admin endpoints."""

from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class SupabaseAdminError(Exception):
    """Raised when the GoTrue admin API returns a non-success response."""

    def __init__(self, message: str, *, status_code: int, detail: dict[str, Any] | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class SupabaseAdminUnavailableError(Exception):
    """Raised when GoTrue is unreachable (network error) or the service-role key is missing."""

    def __init__(self, message: str = "Supabase admin service unavailable"):
        self.message = message
        super().__init__(message)


class SupabaseAdminService:
    """Privileged admin-API client. Backed by a reused httpx.AsyncClient."""

    def __init__(self) -> None:
        self._base_url = settings.supabase_url
        self._service_role_key = settings.supabase_service_role_key
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def delete_user(self, user_id: str) -> None:
        """DELETE /auth/v1/admin/users/{user_id}. 404 is treated as success."""
        if not self._service_role_key:
            raise SupabaseAdminUnavailableError(
                "Supabase service role key is not configured"
            )

        url = f"{self._base_url}/auth/v1/admin/users/{user_id}"
        headers = {
            "Authorization": f"Bearer {self._service_role_key}",
            "apikey": self._service_role_key,
        }

        try:
            resp = await self._client.delete(url, headers=headers)
        except httpx.HTTPError as exc:
            logger.error(
                "supabase_admin_delete_failed", error=str(exc), user_id=user_id
            )
            raise SupabaseAdminUnavailableError(str(exc)) from exc

        if resp.status_code in (200, 204, 404):
            return

        logger.error(
            "supabase_admin_delete_rejected",
            status_code=resp.status_code,
            body=resp.text,
            user_id=user_id,
        )
        raise SupabaseAdminError(
            "GoTrue admin rejected delete",
            status_code=resp.status_code,
            detail={"status": resp.status_code},
        )
