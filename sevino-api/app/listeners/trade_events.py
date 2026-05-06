from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.listeners.base_sse import BaseSSEListener
from app.services.trade_events import handle_trade_update, reconcile_open_orders

logger = structlog.get_logger(__name__)


# Short threshold versus account/transfer status: the trade events stream
# covers every Sevino user's order activity, so during market hours we expect
# a steady pulse. 30 minutes is loose enough to avoid false alarms from
# genuinely quiet periods (lunch-hour lulls, low-activity tickers), tight
# enough to notice when the stream has actually died. Outside market hours
# this will alert spuriously — the liveness cron can be made market-hour-
# aware once we have a second signal to distinguish "Alpaca is silent" from
# "we lost the stream".
_SILENCE_THRESHOLD_SECONDS = 30 * 60


class TradeEventsListener(BaseSSEListener):
    """SSE consumer for Alpaca Broker API's ``/v2/events/trades`` stream.

    Per the Broker API docs, ``/v2/events/trades`` is the sole real-time
    channel for order lifecycle events on the Broker API — there is no
    WebSocket equivalent (the Trading-API ``/stream`` WebSocket uses a
    different auth model and is not available to broker partners). The v1
    endpoint is legacy and not available to new Broker API partners, so v2
    is required for us. Every trade-update variant (``new``, ``fill``,
    ``partial_fill``, ``canceled``, ``rejected``, …) arrives on this
    connection and carries the full ``order`` object, which
    :func:`handle_trade_update` uses to UPDATE the existing ``order_events``
    row in place.
    """

    stream_name = "trade_events_sse"
    endpoint_path = "/v2/events/trades"
    silence_threshold_seconds = _SILENCE_THRESHOLD_SECONDS
    # ``/v2/events/trades`` exposes the ULID directly on the top-level
    # ``event_id`` field and accepts ``?since_id=<ulid>`` on resume — not
    # the ``event_ulid`` / ``since_ulid`` pair used by the v1-style
    # account-status / transfer / journal / NTA streams. The default base-
    # class fields are wrong for this endpoint; overriding is required.
    resume_field = "event_id"
    resume_param = "since_id"

    async def handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        # event_type is unused: trade events route on data["order"]["status"]
        # because every variant (``fill``, ``partial_fill``, ``new``,
        # ``canceled``, ``replaced``, …) carries the full order under
        # ``order``, so the handler picks up the current state without
        # caring which SSE event type fired.
        await handle_trade_update(session, data, wire_format="sse")

    async def on_reconnect(self) -> None:
        """Sweep every non-terminal order through Alpaca REST so any fill /
        cancel / reject that slipped past ``since_id`` replay lands on the
        row. Runs in its own session — the per-event transaction hasn't
        been opened yet."""
        async with async_session() as session:
            try:
                await reconcile_open_orders(
                    session, self._broker, stream_name=self.stream_name
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
