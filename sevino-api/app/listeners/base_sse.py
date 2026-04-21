import abc
import asyncio
import random
import time
from typing import Any

import httpx
import httpx_sse
import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.repositories.sse_checkpoint import SseCheckpointRepository
from app.services.alpaca_broker import AlpacaBrokerService

logger = structlog.get_logger(__name__)


# Exponential backoff tuning. Sleeps min(2^attempt, max) + jitter. Jitter
# exists so parallel listeners don't all reconnect in lockstep after a
# shared upstream blip.
_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0
_BACKOFF_JITTER_SECONDS = 5.0

# Read timeout is None (infinite) because SSE streams are long-lived by
# design — the server holds the connection open indefinitely. Connect
# timeout is bounded so a dead peer fails fast into the reconnect loop.
_CONNECT_TIMEOUT_SECONDS = 10.0


class BaseSSEListener(abc.ABC):
    """Long-lived Alpaca SSE consumer with checkpoint resume + auto-reconnect.

    Subclasses set ``stream_name``, ``endpoint_path``, and
    ``silence_threshold_seconds``, and implement :meth:`handle_event`. The
    base class owns every piece of transport plumbing:

    * Alpaca OAuth bearer via :class:`AlpacaBrokerService`
    * Checkpoint read on connect (``?<resume_param>=<last_event_id>``)
    * Event parsing (via ``httpx_sse``) and dispatch
    * Per-event correlation ID bound to ``structlog.contextvars``
    * Sentry breadcrumbs on connect / disconnect / parse failure
    * ``last_message_received_at`` (monotonic) for the liveness cron
    * Exponential-backoff-with-jitter reconnect, no retry cap
    * Graceful shutdown on :class:`asyncio.CancelledError`

    An instance is a long-running :class:`asyncio.Task` spawned in the ARQ
    worker's ``on_startup`` hook. :meth:`run` exits only on cancellation.

    The defaults for ``resume_field`` and ``resume_param`` match Alpaca's
    legacy endpoints (``/v1/events/accounts/status``, transfers, journal
    status, NTA), which expose a ULID in a separate ``event_ulid`` JSON
    field and accept ``?since_ulid=<ulid>`` on resume. Subclasses for
    already-migrated endpoints (``/v2/events/trades``, admin actions) must
    override both to ``"event_id"`` / ``"since_id"`` because those
    endpoints put the ULID directly in ``event_id`` and the query param
    name was not renamed. See docs/architecture.md.
    """

    stream_name: str
    endpoint_path: str
    silence_threshold_seconds: int
    resume_field: str = "event_ulid"
    resume_param: str = "since_ulid"

    def __init__(self, broker: AlpacaBrokerService) -> None:
        self._broker = broker
        # Seed to "now" so liveness doesn't alarm before the first event.
        self.last_message_received_at: float = time.monotonic()

    @abc.abstractmethod
    async def handle_event(
        self,
        session: AsyncSession,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Process one event. Runs inside the same transaction as the
        checkpoint upsert — raising rolls back both and the loop continues."""

    async def run(self) -> None:
        """Main loop. Connect, stream, reconnect forever. Returns only on
        :class:`asyncio.CancelledError`."""
        attempt = 0
        timeout = httpx.Timeout(None, connect=_CONNECT_TIMEOUT_SECONDS)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while True:
                try:
                    await self._stream_once(client)
                    attempt = 0
                except asyncio.CancelledError:
                    logger.info(
                        "sse_listener_cancelled", stream=self.stream_name
                    )
                    raise
                except Exception as exc:
                    logger.warning(
                        "sse_listener_disconnected",
                        stream=self.stream_name,
                        error=str(exc),
                        exc_type=type(exc).__name__,
                        attempt=attempt,
                    )
                    sentry_sdk.add_breadcrumb(
                        category="sse",
                        level="warning",
                        message=f"{self.stream_name} disconnected: {exc}",
                    )
                delay = self._backoff(attempt)
                attempt += 1
                await asyncio.sleep(delay)

    async def _stream_once(self, client: httpx.AsyncClient) -> None:
        """Open one SSE connection and process events until it drops."""
        checkpoint = await self._load_checkpoint()
        token = await self._broker._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }
        params = {self.resume_param: checkpoint} if checkpoint else None
        url = f"{settings.alpaca_base_url}{self.endpoint_path}"

        logger.info(
            "sse_listener_connecting",
            stream=self.stream_name,
            checkpoint=checkpoint,
        )
        sentry_sdk.add_breadcrumb(
            category="sse",
            level="info",
            message=f"{self.stream_name} connecting",
            data={"checkpoint": checkpoint},
        )

        async with httpx_sse.aconnect_sse(
            client, "GET", url, headers=headers, params=params,
        ) as event_source:
            # httpx-sse doesn't validate the HTTP status before iterating;
            # it only checks Content-Type inside aiter_sse. A non-200 response
            # that happens to carry `Content-Type: text/event-stream` (e.g. a
            # proxied 5xx error page) would otherwise drain to zero events
            # and cause _stream_once to return normally — which resets our
            # backoff counter and produces a tight rapid-reconnect loop.
            # raise_for_status surfaces real failures as httpx.HTTPStatusError
            # so they flow through the standard backoff path in run().
            event_source.response.raise_for_status()
            logger.info("sse_listener_connected", stream=self.stream_name)
            sentry_sdk.add_breadcrumb(
                category="sse",
                level="info",
                message=f"{self.stream_name} connected",
            )
            async for sse in event_source.aiter_sse():
                self.last_message_received_at = time.monotonic()
                await self._process_event(sse)

    async def _process_event(self, sse: httpx_sse.ServerSentEvent) -> None:
        """Atomic: subclass handler + checkpoint upsert in one transaction."""
        event_type = sse.event

        # Parse first so we can pull the ULID out of the payload. Reading
        # from parsed JSON (rather than the SSE wire `id:` line) makes us
        # independent of whether Alpaca populates `id:` on a given endpoint.
        try:
            data = sse.json() if sse.data else {}
        except Exception as exc:
            logger.warning(
                "sse_parse_failed",
                stream=self.stream_name,
                error=str(exc),
            )
            sentry_sdk.add_breadcrumb(
                category="sse",
                level="warning",
                message=f"{self.stream_name} parse failed",
            )
            sentry_sdk.capture_exception(exc)
            return

        event_ulid = data.get(self.resume_field) if isinstance(data, dict) else None
        correlation_id = (
            f"sse-{self.stream_name}-{event_ulid}"
            if event_ulid
            else f"sse-{self.stream_name}"
        )

        with (
            structlog.contextvars.bound_contextvars(
                correlation_id=correlation_id,
                stream=self.stream_name,
                event_type=event_type,
            ),
            sentry_sdk.new_scope() as scope,
        ):
            # Tags are searchable in the Sentry UI (e.g. "show all errors on
            # trade_events_sse"); context is attached to the event body.
            scope.set_tag("sse_stream", self.stream_name)
            scope.set_tag("sse_event_type", event_type or "unknown")
            if event_ulid:
                scope.set_tag("sse_event_id", event_ulid)
            scope.set_context(
                "sse_event",
                {
                    "stream": self.stream_name,
                    "event_id": event_ulid,
                    "event_type": event_type,
                    "correlation_id": correlation_id,
                },
            )

            async with async_session() as session:
                try:
                    await self.handle_event(session, event_type, data)
                    if event_ulid:
                        await SseCheckpointRepository.upsert(
                            session, self.stream_name, event_ulid
                        )
                    await session.commit()
                except Exception as exc:
                    # Expected handler errors: log, roll back, move on.
                    await session.rollback()
                    logger.error(
                        "sse_handler_failed",
                        error=str(exc),
                        exc_type=type(exc).__name__,
                    )
                    sentry_sdk.capture_exception(exc)
                except BaseException:
                    # CancelledError (and SystemExit/KeyboardInterrupt) bypass
                    # the Exception arm. Roll back explicitly so we don't rely
                    # on SQLAlchemy's shield-on-close to clean up an open
                    # transaction during worker shutdown, then re-raise so the
                    # cancellation propagates up through the listener loop.
                    # Intentionally NOT captured to Sentry — shutdown cancels
                    # fire on every deploy and would be constant noise.
                    await session.rollback()
                    raise

    async def _load_checkpoint(self) -> str | None:
        async with async_session() as session:
            row = await SseCheckpointRepository.get(session, self.stream_name)
        return row.last_event_id if row else None

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = min(
            _BACKOFF_INITIAL_SECONDS * (2**attempt), _BACKOFF_MAX_SECONDS
        )
        return base + random.uniform(0, _BACKOFF_JITTER_SECONDS)
