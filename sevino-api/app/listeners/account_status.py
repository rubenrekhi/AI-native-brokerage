from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.listeners.base_sse import BaseSSEListener
from app.services.account_status import apply_account_status_change

logger = structlog.get_logger(__name__)


def _parse_alpaca_timestamp(value: Any) -> datetime | None:
    # Alpaca emits RFC3339 strings like "2023-10-13T13:34:28.30629Z". Python's
    # datetime.fromisoformat handles the "Z" suffix natively from 3.11+.
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        # Format drift worth surfacing: the payload carried an ``at`` string
        # we couldn't parse, so the caller is about to fall back to now() for
        # any timestamp-driven write. Log loudly enough to notice — if Alpaca
        # ever changes the format, we want a trail rather than silent drift.
        logger.warning("account_status_unparseable_at", raw=value)
        return None


class AccountStatusListener(BaseSSEListener):
    """Alpaca account-lifecycle SSE listener (SEV-213).

    Consumes ``/v1/events/accounts/status`` and UPDATEs the matching
    ``brokerage_accounts`` row whenever KYC or account state changes. The
    base class owns connect, reconnect, checkpointing, liveness, and
    comment/heartbeat handling — this subclass only implements the payload
    contract.

    Resume fields use base-class defaults (``event_ulid`` / ``since_ulid``):
    Alpaca emits ``event_ulid`` alongside the integer ``event_id`` on this
    endpoint and recommends ``since_ulid`` for forward-compat when the
    remaining legacy streams finish migrating to ULIDs.
    """

    stream_name = "account_status_sse"
    endpoint_path = "/v1/events/accounts/status"

    async def handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        # The base class passes parsed JSON straight through and only
        # ``isinstance``-guards its own ULID extraction (base_sse.py:342). If
        # Alpaca ever hands us a non-object payload, ``data.get`` would raise
        # AttributeError and we'd lose the structured "malformed_event"
        # breadcrumb to a generic exception capture. Fold the type check into
        # the main guard so every bad shape hits one warning path.
        if (
            not isinstance(data, dict)
            or not data.get("account_id")
            or not data.get("status_to")
        ):
            logger.warning(
                "account_status_malformed_event",
                data_type=type(data).__name__,
                data_keys=sorted(data.keys()) if isinstance(data, dict) else None,
            )
            return
        alpaca_account_id = data["account_id"]
        new_status = data["status_to"]

        await apply_account_status_change(
            session,
            alpaca_account_id=alpaca_account_id,
            new_status=new_status,
            kyc_results=data.get("kyc_results"),
            event_time=_parse_alpaca_timestamp(data.get("at")),
            alpaca=self._broker,
        )
