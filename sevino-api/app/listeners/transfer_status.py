from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.listeners.base_sse import BaseSSEListener
from app.services.alpaca_broker import AlpacaBrokerService
from app.services.transfer_status import handle_transfer_status_change

logger = structlog.get_logger(__name__)


def _parse_alpaca_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("transfer_status_unparseable_at", raw=value)
        return None


class TransferStatusListener(BaseSSEListener):
    """Alpaca funding-status SSE listener.

    Consumes ``/v2/events/funding/status``, which multiplexes lifecycle
    events for three entity types: ``Transfer``, ``BankRelationship``, and
    ``WireBank``. (``FundingWallet`` is explicitly NOT on this stream per
    Alpaca's funding-wallet support docs — those updates surface via the
    GET funding wallet transfers endpoint.) This listener acts only on
    ``Transfer`` events; other entity types are debug-logged and skipped
    so future tickets can hook them in without changing the wire-level
    connection.

    The original ticket (SEV-214) refers to ``/v1/events/transfers/status``,
    but that endpoint returns HTTP 410 ("Endpoint is deprecated") for new
    broker partners — confirmed by the SEV-594 sandbox probe. The v2
    funding stream is the only supported path.

    Resume schema overrides (vs the base-class defaults used by the v1
    legacy account-status stream): v2 funding puts the ULID directly on
    the top-level ``event_id`` field and accepts ``?since_id=<ulid>`` on
    reconnect — same convention as ``/v2/events/trades``. The actual
    payload shape was captured during the SEV-594 probe; see
    ``.context/v2_funding_event_sample.json`` for the verbatim sample.
    """

    stream_name = "funding_status_sse"
    endpoint_path = "/v2/events/funding/status"
    resume_field = "event_id"
    resume_param = "since_id"

    def __init__(self, broker: AlpacaBrokerService, redis: aioredis.Redis) -> None:
        super().__init__(broker)
        self._redis = redis

    async def handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if not isinstance(data, dict):
            logger.warning(
                "transfer_status_malformed_event",
                data_type=type(data).__name__,
                data_keys=None,
            )
            return

        # Filter: the v2 funding stream multiplexes BankRelationship and
        # WireBank events alongside Transfer events. Only Transfer affects
        # user balances — surface the rest at debug so they don't disappear
        # silently, but don't bust caches on a bank-relationship status flip.
        entity_type = data.get("entity_type")
        if entity_type != "Transfer":
            logger.debug(
                "transfer_status_skipping_entity",
                entity_type=entity_type,
                event_id=data.get(self.resume_field),
            )
            return

        # v2 funding renamed the transfer UUID field from ``transfer_id``
        # (v1) to the generic ``entity_id`` — verified by SEV-594 capture.
        # No fallback because the v1 endpoint is dead for us (410).
        alpaca_account_id = data.get("account_id")
        entity_id = data.get("entity_id")
        status_to = data.get("status_to")
        if not alpaca_account_id or not entity_id or not status_to:
            logger.warning(
                "transfer_status_malformed_event",
                data_type=type(data).__name__,
                data_keys=sorted(data.keys()),
            )
            return

        await handle_transfer_status_change(
            session,
            self._redis,
            alpaca_account_id=alpaca_account_id,
            transfer_id=entity_id,
            status_from=data.get("status_from"),
            status_to=status_to,
            event_time=_parse_alpaca_timestamp(data.get("at")),
        )
