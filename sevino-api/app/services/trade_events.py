"""Trade-event processing for Alpaca Broker API's ``/v2/events/trades`` SSE
stream. The live SSE listener and the ``on_reconnect`` REST reconcile sweep
both dispatch through :func:`handle_trade_update`; UPDATE idempotency plus
the ordinal check in :data:`STATUS_ORDER` is the entire deduplication story
— no Redis locks, no separate dedup keys.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.repositories.order_event import OrderEventRepository
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)


# Alpaca's trade_updates lifecycle, ordered low→high. The handler only writes
# when the incoming status' ordinal is strictly greater than the stored
# ordinal, which stops the ``on_reconnect`` REST reconcile sweep's
# latest-state write from being regressed by the subsequent ``since_id``
# SSE replay of earlier, stale intermediate statuses. Source: Alpaca Broker
# API "Order Lifecycle" docs — the full set is kept here verbatim so an
# unknown status surfaces as a missing-key lookup rather than silently
# being treated as either earlier or later than the current state.
#
# Rationale for terminal ranking: ``filled`` sits above ``partially_filled``
# because a fill event supersedes every prior partial. ``canceled`` /
# ``expired`` / ``rejected`` share the max ordinal because they are mutually
# exclusive terminal outcomes — if one lands, no other terminal transition
# can follow, so ``_TERMINAL_RANK`` below enforces a write-once policy at
# rank 6.
STATUS_ORDER: dict[str, int] = {
    "new": 0,
    "held": 1,
    "accepted": 1,
    "accepted_for_bidding": 1,
    "pending_new": 1,
    "pending_replace": 2,
    "pending_cancel": 2,
    "replaced": 3,
    "suspended": 3,
    "calculated": 3,
    "stopped": 3,
    "partially_filled": 4,
    "done_for_day": 5,
    "filled": 6,
    "canceled": 6,
    "expired": 6,
    "rejected": 6,
}
# Rank at which statuses are mutually exclusive and write-once. Transitions
# at ranks below this are permitted to move laterally (e.g. ``pending_cancel``
# → ``pending_replace``) because those are legitimately unordered Alpaca
# states, but once a row reaches a terminal (``filled``, ``canceled``,
# ``expired``, ``rejected``) no other terminal may overwrite it.
_TERMINAL_RANK = 6


def _status_rank(status: str | None) -> int | None:
    """Return the lifecycle ordinal for a status, or ``None`` if unknown.
    Unknown statuses are treated as "don't skip" by the caller — we'd rather
    apply a new-to-us status than silently drop it."""
    if status is None:
        return None
    return STATUS_ORDER.get(status)


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        # Alpaca emits RFC 3339 with a trailing ``Z``; fromisoformat accepts
        # ``+00:00`` on every supported Python version.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_order(
    payload: dict[str, Any],
    *,
    wire_format: Literal["sse", "rest"] | None = None,
) -> dict[str, Any] | None:
    """Trade events wrap the order under ``order``; REST ``get_order`` returns
    the order object directly. Accept both shapes so the reconcile sweep and
    the live handler can share this function.

    When ``wire_format == "sse"`` the wrapper is required: a missing or
    non-dict ``order`` key indicates a malformed event and the caller is
    expected to skip rather than treat the envelope itself as the order
    body (which would otherwise let the envelope's ``event_id`` masquerade
    as an Alpaca order id and silently update the wrong row). Returns
    ``None`` to signal that case.
    """
    order = payload.get("order")
    if isinstance(order, dict):
        return order
    if wire_format == "sse":
        return None
    return payload


def _should_skip_status(
    *, new_status: str | None, current_status: str | None
) -> bool:
    """Decide whether to skip a status transition based on the lifecycle order.

    Invariant: write only when the incoming status is strictly newer, OR a
    legitimately unordered peer at a non-terminal rank. At the terminal rank
    statuses are mutually exclusive and write-once, so peer equality there
    also skips. Unknown statuses (not in :data:`STATUS_ORDER`) are not
    skipped — better to apply a new-to-us status and surface it in logs than
    silently drop it.
    """
    if new_status is None or new_status == current_status:
        return False
    incoming_rank = _status_rank(new_status)
    current_rank = _status_rank(current_status)
    if incoming_rank is None or current_rank is None:
        return False
    if incoming_rank < current_rank:
        return True
    return (
        incoming_rank == current_rank
        and incoming_rank == _TERMINAL_RANK
    )


async def handle_trade_update(
    session: AsyncSession,
    event_payload: dict[str, Any],
    *,
    wire_format: Literal["sse", "rest"] | None = None,
) -> None:
    """Apply one trade update — from the live SSE stream or the REST
    reconcile sweep — to the matching ``order_events`` row.

    ``wire_format`` is a discriminator for how the order body is shaped:
    SSE payloads always wrap the order under ``order``; REST ``get_order``
    returns it at the top level. When ``"sse"`` is passed and the wrapper
    is missing the event is treated as malformed (logged + Sentry-surfaced
    + skipped) so a broken envelope can't silently drive a same-keyed
    field on the envelope into ``handle_trade_update`` as if it were the
    order id.

    Skip conditions (each returns without writing, without raising):

    * SSE payload missing an ``order`` wrapper — malformed event.
    * The embedded order has no ``id`` — malformed payload.
    * No ``order_events`` row matches the Alpaca order id — the order belongs
      to an account we don't manage, or predates our storage.
    * The incoming status' ordinal in :data:`STATUS_ORDER` is strictly less
      than the stored status' ordinal, or both are at the terminal rank with
      different statuses (terminal transitions are mutually exclusive).

    When not skipped, UPDATEs ``status`` plus any fill fields present on the
    payload. The caller commits the transaction (see ``BaseSSEListener``).
    """
    order = _extract_order(event_payload, wire_format=wire_format)
    if order is None:
        logger.warning(
            "trade_update_malformed_sse_payload",
            payload_keys=sorted(event_payload.keys()),
        )
        sentry_sdk.capture_message(
            "Trade-events SSE payload missing 'order' wrapper",
            level="warning",
        )
        return

    alpaca_order_id = order.get("id")
    if not alpaca_order_id:
        logger.warning("trade_update_missing_order_id", payload=event_payload)
        return

    row = await OrderEventRepository.get_by_alpaca_order_id(
        session, alpaca_order_id
    )
    if row is None:
        logger.info(
            "trade_update_unknown_order",
            alpaca_order_id=alpaca_order_id,
        )
        return

    new_status = order.get("status")
    if _should_skip_status(new_status=new_status, current_status=row.status):
        logger.info(
            "trade_update_skipped_out_of_order",
            alpaca_order_id=alpaca_order_id,
            current_status=row.status,
            incoming_status=new_status,
        )
        return

    if new_status is not None:
        row.status = new_status

    filled_avg_price = _parse_decimal(order.get("filled_avg_price"))
    if filled_avg_price is not None:
        row.filled_avg_price = filled_avg_price

    filled_qty = _parse_decimal(order.get("filled_qty"))
    if filled_qty is not None:
        row.filled_qty = filled_qty

    filled_at = _parse_datetime(order.get("filled_at"))
    if filled_at is not None:
        row.filled_at = filled_at

    await session.flush()

    logger.info(
        "trade_update_applied",
        alpaca_order_id=alpaca_order_id,
        status=row.status,
        filled_qty=str(row.filled_qty) if row.filled_qty is not None else None,
        filled_avg_price=(
            str(row.filled_avg_price)
            if row.filled_avg_price is not None
            else None
        ),
    )


async def reconcile_open_orders(
    session: AsyncSession,
    broker: AlpacaBrokerService,
    *,
    stream_name: str,
) -> int:
    """Refresh every non-terminal ``order_events`` row from Alpaca REST. Used
    by the trade-events listener's ``on_reconnect`` hook so any transition
    that happened while we were disconnected (and fell outside Alpaca's
    ``since_id`` replay window) still lands on the row.

    Per-order failures are swallowed — one unreachable order shouldn't block
    the rest of the sweep or the listener coming back online. Each apply runs
    in its own session + transaction so a failed flush on one row can't
    poison the rest of the sweep via ``PendingRollbackError``. The caller's
    ``session`` backs only the initial read query.

    ``stream_name`` is the Sentry tag the live listener uses for its captures
    — passed in so this sweep's escalations are filterable by the same key.

    Returns the number of orders successfully refreshed.
    """
    open_orders = await OrderEventRepository.get_open_with_alpaca_account_id(
        session
    )
    if not open_orders:
        logger.info("trade_reconcile_nothing_to_refresh")
        return 0

    logger.info("trade_reconcile_starting", open_order_count=len(open_orders))
    refreshed = 0
    fetch_failures = 0
    id_mismatch_failures = 0
    flush_failures = 0
    for open_row in open_orders:
        order = open_row.order
        alpaca_account_id = open_row.alpaca_account_id
        alpaca_order_id = order.alpaca_order_id
        try:
            remote = await broker.get_order(
                alpaca_account_id, alpaca_order_id
            )
        except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
            fetch_failures += 1
            logger.warning(
                "trade_reconcile_fetch_failed",
                alpaca_order_id=alpaca_order_id,
                error=str(exc),
            )
            sentry_sdk.add_breadcrumb(
                category="trade_reconcile",
                level="warning",
                message=f"fetch failed for {alpaca_order_id}: {exc}",
            )
            continue

        # Defense against a broker response whose ``id`` doesn't match the
        # one we asked for: ``handle_trade_update`` looks up the row by
        # ``id`` alone (it has no user context on the live SSE path), so a
        # mismatched response could UPDATE another user's row. Recorded as
        # a breadcrumb here and aggregated into the sweep-end Sentry event
        # below — emitting one ``capture_message`` per bad row would fan
        # out to N events for one bad sweep.
        if remote.get("id") != alpaca_order_id:
            id_mismatch_failures += 1
            logger.error(
                "trade_reconcile_id_mismatch",
                requested_alpaca_order_id=alpaca_order_id,
                returned_alpaca_order_id=remote.get("id"),
            )
            sentry_sdk.add_breadcrumb(
                category="trade_reconcile",
                level="error",
                message=(
                    f"id mismatch: requested {alpaca_order_id}, "
                    f"got {remote.get('id')}"
                ),
            )
            continue

        # Per-order session so a failed flush (integrity error, DB blip)
        # can't leave the sweep's outer session in ``PendingRollbackError``
        # state and cascade-fail every subsequent row.
        async with async_session() as apply_session:
            try:
                await handle_trade_update(
                    apply_session, remote, wire_format="rest"
                )
                await apply_session.commit()
                refreshed += 1
            except Exception as exc:
                await apply_session.rollback()
                flush_failures += 1
                logger.error(
                    "trade_reconcile_apply_failed",
                    alpaca_order_id=alpaca_order_id,
                    error=str(exc),
                )
                sentry_sdk.add_breadcrumb(
                    category="trade_reconcile",
                    level="error",
                    message=f"apply failed for {alpaca_order_id}: {exc}",
                )

    apply_failures = id_mismatch_failures + flush_failures

    # Sweep-wide alert: any failure during reconcile is operationally
    # interesting — per-order breadcrumbs don't surface as Sentry events on
    # their own, so a sustained outage (Alpaca returning the wrong ids for
    # half the sweep, or a pgwire blip flushing a quarter of rows) would
    # otherwise stay silent. Emit one scoped ``capture_message`` per sweep
    # with the failure breakdown so ops can distinguish "every fetch failed"
    # (Alpaca down, expired OAuth, wrong base URL) from a partial outage,
    # and id-mismatch from flush errors.
    if fetch_failures > 0 or apply_failures > 0:
        scanned = len(open_orders)
        all_fetch_failed = fetch_failures == scanned and apply_failures == 0
        alert_type = (
            "trade_reconcile_empty"
            if all_fetch_failed
            else "trade_reconcile_partial"
        )
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("sse_stream", stream_name)
            scope.set_tag("alert_type", alert_type)
            scope.set_context(
                "trade_reconcile",
                {
                    "open_order_count": scanned,
                    "fetch_failures": fetch_failures,
                    "id_mismatch_failures": id_mismatch_failures,
                    "flush_failures": flush_failures,
                    "refreshed": refreshed,
                },
            )
            if all_fetch_failed:
                message = (
                    f"Trade-events reconcile sweep: all {fetch_failures} "
                    "Alpaca fetches failed"
                )
            else:
                parts: list[str] = []
                if fetch_failures:
                    parts.append(f"{fetch_failures} fetch")
                if id_mismatch_failures:
                    parts.append(f"{id_mismatch_failures} id-mismatch")
                if flush_failures:
                    parts.append(f"{flush_failures} flush")
                message = (
                    f"Trade-events reconcile sweep: "
                    f"{', '.join(parts)} failure(s) across {scanned} orders"
                )
            sentry_sdk.capture_message(message, level="warning")

    logger.info(
        "trade_reconcile_complete",
        scanned=len(open_orders),
        refreshed=refreshed,
        fetch_failures=fetch_failures,
        id_mismatch_failures=id_mismatch_failures,
        flush_failures=flush_failures,
    )
    return refreshed
