import abc
import asyncio
import random
import re
import time
from typing import Any

import httpx
import httpx_sse
import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

# Private imports: httpx_sse.aiter_sse() silently filters SSE comment lines
# (``:...``), but Alpaca uses comments for :heartbeat (liveness), slow-client
# warnings ("dropped N messages"), and v2 internal-server-error notices — all
# of which we need to surface. There's no public path to get them.
#
# Using both decoders keeps our line-splitting identical to upstream
# aiter_sse(). httpx.Response.aiter_lines() uses stdlib str.splitlines(),
# which splits on \x0b \x0c \x1c \x1d \x1e \x85   in addition
# to the SSE-spec-allowed \r \n \r\n — feeding that into SSEDecoder would
# be a silent correctness divergence on any payload containing those
# characters. SSELineDecoder is spec-compliant.
#
# Both classes have stable, minimal interfaces and have been unchanged
# across httpx_sse releases. If either moves or changes shape on upgrade,
# inline ~40 LoC of decoder.
from httpx_sse._decoders import SSEDecoder, SSELineDecoder  # noqa: PLC2701

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

# Matches Alpaca's slow-client warning: ": you are reading too slowly,
# dropped 10000 messages". We pull the number out for a Sentry tag so ops
# can filter/aggregate drop events across streams. IGNORECASE is belt-
# and-braces in case Alpaca ever rephrases with different capitalization —
# on a miss, the warning log + breadcrumb still fire unconditionally;
# only the searchable drop-count tag would be lost.
_DROPPED_RE = re.compile(r"dropped\s+(\d+)\s+messages", re.IGNORECASE)

# Comment bodies Alpaca sends on healthy connections. Observed in sandbox:
# * "heartbeat" — periodic keepalive.
# * "welcome to the Alpaca events" — sent once on every successful connect.
# Members of this set still bump ``last_message_received_at`` inside
# ``_process_comment`` — they just skip the warning log + Sentry breadcrumb
# that every other comment triggers. Otherwise the welcome banner would fire
# a breadcrumb on every reconnect and bury real diagnostics. Anything NOT in
# this set flows through the warning path so genuinely new comments from
# Alpaca surface loudly.
_BENIGN_COMMENTS = frozenset({"heartbeat", "welcome to the Alpaca events"})


class BaseSSEListener(abc.ABC):
    """Long-lived Alpaca SSE consumer with checkpoint resume + auto-reconnect.

    Subclasses set ``stream_name``, ``endpoint_path``, and
    ``silence_threshold_seconds``, and implement :meth:`handle_event`. The
    base class owns every piece of transport plumbing:

    * Alpaca OAuth bearer via :class:`AlpacaBrokerService`
    * Checkpoint read on connect (``?<resume_param>=<last_event_id>``)
    * Event parsing (via ``httpx_sse.SSEDecoder``) and dispatch
    * Surfacing of SSE comment lines (``:heartbeat`` and diagnostic
      comments like "dropped N messages" / "internal server error")
    * Per-event correlation ID bound to ``structlog.contextvars``
    * Sentry breadcrumbs on connect / disconnect / parse failure
    * ``last_message_received_at`` (monotonic) for the liveness cron —
      bumped on real events *and* on heartbeat comments so quiet streams
      don't false-alarm
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
    # 90s ≈ six missed 15s heartbeats of headroom (15s is a common SSE-API
    # convention, not spec-mandated; Alpaca's actual cadence is not
    # documented — measure via the ticketed sandbox probe and revisit if
    # wildly different). Alpaca's FAQ explicitly guarantees they never
    # stop responding, so this threshold is detecting client-side
    # connection loss, not upstream going silent. Subclasses may override
    # per-stream.
    silence_threshold_seconds: int = 90
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

            # aiter_sse() would normally guard the content-type for us; since
            # we iterate raw lines below (to surface comment lines), reproduce
            # the check inline. Same error type so callers can't tell.
            content_type = event_source.response.headers.get(
                "content-type", ""
            ).partition(";")[0]
            if "text/event-stream" not in content_type:
                raise httpx_sse.SSEError(
                    "Expected response header Content-Type to contain "
                    f"'text/event-stream', got {content_type!r}"
                )

            logger.info("sse_listener_connected", stream=self.stream_name)
            sentry_sdk.add_breadcrumb(
                category="sse",
                level="info",
                message=f"{self.stream_name} connected",
            )

            # Iterate lines via SSELineDecoder (spec-compliant splitter —
            # httpx.Response.aiter_lines uses looser stdlib splitlines()
            # semantics) and feed them to SSEDecoder ourselves. Lines
            # starting with ':' are SSE comments — SSEDecoder drops them
            # silently, so we intercept first. Heartbeats + diagnostics
            # flow to _process_comment (which bumps liveness itself); real
            # events flow to _process_event. The liveness bump for real
            # events happens here; for comments it happens inside
            # _process_comment.
            line_decoder = SSELineDecoder()
            event_decoder = SSEDecoder()
            async for chunk in event_source.response.aiter_text():
                for line in line_decoder.decode(chunk):
                    if line.startswith(":"):
                        self._process_comment(line)
                        continue
                    sse = event_decoder.decode(line)
                    if sse is not None:
                        self.last_message_received_at = time.monotonic()
                        await self._process_event(sse)
            # Flush any trailing partial line — upstream aiter_sse() does
            # the same on iterator exit. In practice Alpaca's stream never
            # terminates cleanly (the connection drops instead), so this
            # is defensive.
            for line in line_decoder.flush():
                if line.startswith(":"):
                    self._process_comment(line)
                    continue
                sse = event_decoder.decode(line)
                if sse is not None:
                    self.last_message_received_at = time.monotonic()
                    await self._process_event(sse)

    def _process_comment(self, raw_line: str) -> None:
        """Handle one SSE comment line.

        Alpaca uses comment lines for four things we care about:

        * ``:heartbeat`` — keepalive on idle streams. Only signal proving
          the TCP connection is still alive when no business events are
          flowing. Bumping ``last_message_received_at`` here is the reason
          we bother reading comments at all — without it, the liveness
          cron false-alarms on any quiet account-status stream.
        * ``: welcome to the Alpaca events`` — emitted once per successful
          connect on this endpoint. Benign; treated like a heartbeat so it
          doesn't spam Sentry breadcrumbs on every reconnect.
        * ``: you are reading too slowly, dropped N messages`` — slow
          consumer warning. Raised as its own Sentry event with the drop
          count as a searchable tag, since this is a critical op signal
          even when the connection doesn't later drop.
        * ``: internal server error`` — v2/v2beta1 endpoints send this
          before closing the connection. Logged + breadcrumbed so it
          shows up in the context of the subsequent disconnect capture.
        """
        # Per SSE spec, a comment line is ':' optionally followed by a
        # single space, then the body. Alpaca sends ``:heartbeat`` (no
        # space) but ``: internal server error`` and ``: you are reading
        # too slowly ...`` (with space). Normalize by stripping leading
        # whitespace after the colon.
        comment = raw_line[1:].lstrip(" ")

        # Bump liveness for EVERY comment, including heartbeats — that's
        # the whole point of this method.
        self.last_message_received_at = time.monotonic()

        if comment in _BENIGN_COMMENTS:
            logger.info(
                "sse_benign_comment", stream=self.stream_name, comment=comment
            )
            return

        logger.warning(
            "sse_diagnostic_comment",
            stream=self.stream_name,
            comment=comment,
        )
        sentry_sdk.add_breadcrumb(
            category="sse",
            level="warning",
            message=f"{self.stream_name} diagnostic: {comment}",
            data={"stream": self.stream_name, "comment": comment},
        )

        match = _DROPPED_RE.search(comment)
        if match:
            dropped = int(match.group(1))
            with sentry_sdk.new_scope() as scope:
                scope.set_tag("sse_stream", self.stream_name)
                scope.set_tag("sse_dropped_messages", str(dropped))
                scope.set_context(
                    "sse_slow_client",
                    {
                        "stream": self.stream_name,
                        "dropped_messages": dropped,
                    },
                )
                sentry_sdk.capture_message(
                    f"Alpaca dropped {dropped} SSE messages on "
                    f"{self.stream_name}",
                    level="warning",
                )

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

            logger.info(
                "sse_event_received",
                stream=self.stream_name,
                event_type=event_type,
                event_id=event_ulid,
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
