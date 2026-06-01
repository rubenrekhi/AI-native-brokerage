"""Cash interest service: aggregate Alpaca + local DB state into a sweep snapshot."""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.brokerage_account import (
    STATUS_ACTIVE,
    SWEEP_STATUS_ACTIVE,
    SWEEP_STATUS_PENDING_CHANGE,
)
from app.schemas.cash_interest import CashInterestResponse, EnrollmentState
from app.services.alpaca_broker import AlpacaBrokerError, AlpacaBrokerService
from app.services.brokerage import require_brokerage

logger = structlog.get_logger(__name__)

_SWEEP_ACTIVITY_SUB_TYPE = "SWP"
_TWO_PLACES = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


class CashInterestService:
    @staticmethod
    async def get_cash_interest(
        db: AsyncSession,
        *,
        alpaca: AlpacaBrokerService,
        user_id: uuid.UUID,
    ) -> CashInterestResponse:
        brokerage = await require_brokerage(db, user_id)

        alpaca_id = brokerage.alpaca_account_id
        # APY is surfaced on every response so iOS can render a prospective
        # rate even for non-enrolled users ("You could be earning X% APY").
        # Skip the APR-tiers RTT only when no tier name is configured — the
        # lookup would always miss and return zero. Default ALPACA_APR_TIER_NAME
        # is "" until ops sets it post-Alpaca-provision.
        tiers_coro = (
            _safe_get_apr_tiers(alpaca, user_id)
            if settings.alpaca_apr_tier_name
            else _none_coro()
        )
        if brokerage.sweep_status == SWEEP_STATUS_ACTIVE:
            today = datetime.now(timezone.utc).date()
            trading, eod_records, tiers_resp, activities = await asyncio.gather(
                alpaca.get_trading_account(alpaca_id),
                _safe_get_eod(alpaca, alpaca_id, today, user_id),
                tiers_coro,
                _safe_get_activities(alpaca, alpaca_id, user_id),
            )
            this_month_earned = _sum_eod_accrual(eod_records)
            lifetime_realized = _sum_swp_activities(activities)
            # Per spec: lifetime = realized payouts + interest accrued so far
            # this month (not yet credited). The current month resets to zero
            # on payout day, so the total stays roughly monotonic across the
            # SWP boundary.
            lifetime_earned = lifetime_realized + this_month_earned
            interest_fields: dict[str, Any] = {
                "apy": _apy_from_tiers(tiers_resp),
                "this_month_earned": _format_money(this_month_earned),
                "days_accrued": len(eod_records),
                "lifetime_earned": _format_money(lifetime_earned),
            }
        else:
            # Not enrolled: APY is still fetched so the prospective rate
            # renders; earned figures are zero.
            trading, tiers_resp = await asyncio.gather(
                alpaca.get_trading_account(alpaca_id),
                tiers_coro,
            )
            interest_fields = {
                "apy": _apy_from_tiers(tiers_resp),
                "this_month_earned": _format_money(Decimal("0")),
                "days_accrued": 0,
                "lifetime_earned": _format_money(Decimal("0")),
            }

        return CashInterestResponse(
            balance=trading.get("cash", "0"),
            buying_power=trading.get("buying_power", "0"),
            pending_deposits=trading.get("pending_transfer_in", "0"),
            lifetime_since=brokerage.sweep_enrolled_at,
            interest_paid_out=settings.cash_sweep_payout_cadence,
            fdic_insured_limit=settings.cash_sweep_fdic_insured_limit,
            sweep_status=brokerage.sweep_status,
            enrollment_state=_enrollment_state(brokerage),
            **interest_fields,
        )


async def _none_coro() -> None:
    """No-op coroutine used to skip a gather slot without changing call shape."""
    return None


def _enrollment_state(brokerage: Any) -> EnrollmentState:
    """Fold account + sweep status into the client-facing enrollment state.

    iOS keys off this instead of the raw ``sweep_status`` (SEV-655):
    ``unavailable`` when the account isn't ACTIVE yet (the screen hides the
    row), ``active``/``pending`` mirror the sweep, and INACTIVE or NULL on an
    otherwise-active account is ``not_enrolled``.
    """
    if brokerage.account_status != STATUS_ACTIVE:
        return "unavailable"
    if brokerage.sweep_status == SWEEP_STATUS_ACTIVE:
        return "active"
    if brokerage.sweep_status == SWEEP_STATUS_PENDING_CHANGE:
        return "pending"
    return "not_enrolled"


async def _safe_get_eod(
    alpaca: AlpacaBrokerService,
    account_id: str,
    today: date,
    user_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """EOD interest records dated within the current calendar month.

    Pulls records from one day before the first of the month (in case Alpaca
    treats `after` as exclusive) then filters locally on `date >= first_of_month`
    so the boundary is correct regardless of upstream interpretation.

    Degrades to an empty list on AlpacaBrokerError so balance/buying_power
    still render even if reporting is briefly unavailable. Network/auth
    failures (AlpacaBrokerUnavailableError) are intentionally not caught —
    those signal a broader outage and should surface as 503.
    """
    first_of_month = today.replace(day=1)
    after = (first_of_month - timedelta(days=1)).isoformat()
    try:
        records = await alpaca.get_eod_cash_interest(
            account_id=account_id,
            after=after,
            before=today.isoformat(),
        )
    except AlpacaBrokerError as exc:
        logger.warning(
            "cash_interest_eod_unavailable",
            user_id=str(user_id),
            status_code=exc.status_code,
            message=exc.message,
        )
        sentry_sdk.capture_message(
            "cash_interest_eod_unavailable",
            level="warning",
        )
        return []

    boundary = first_of_month.isoformat()
    in_month: list[dict[str, Any]] = []
    for r in records:
        record_date = r.get("date")
        if record_date is None:
            # Schema drift on Alpaca's side. Keep the record (the request was
            # scoped to the month range so it's likely valid) but log so the
            # silent inclusion is observable.
            logger.warning(
                "cash_interest_eod_record_missing_date",
                user_id=str(user_id),
            )
            in_month.append(r)
        elif record_date >= boundary:
            in_month.append(r)
    return in_month


async def _safe_get_apr_tiers(
    alpaca: AlpacaBrokerService, user_id: uuid.UUID
) -> dict[str, Any] | None:
    try:
        return await alpaca.get_apr_tiers()
    except AlpacaBrokerError as exc:
        logger.warning(
            "cash_interest_apr_tiers_unavailable",
            user_id=str(user_id),
            status_code=exc.status_code,
            message=exc.message,
        )
        sentry_sdk.capture_message(
            "cash_interest_apr_tiers_unavailable",
            level="warning",
        )
        return None


async def _safe_get_activities(
    alpaca: AlpacaBrokerService, account_id: str, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    try:
        return await alpaca.get_interest_activities(account_id=account_id)
    except AlpacaBrokerError as exc:
        logger.warning(
            "cash_interest_activities_unavailable",
            user_id=str(user_id),
            status_code=exc.status_code,
            message=exc.message,
        )
        sentry_sdk.capture_message(
            "cash_interest_activities_unavailable",
            level="warning",
        )
        return []


def _sum_eod_accrual(records: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for r in records:
        raw = r.get("account_accrued_interest")
        if raw is None:
            continue
        total += Decimal(raw)
    return total


def _sum_swp_activities(activities: list[dict[str, Any]]) -> Decimal:
    total = Decimal("0")
    for a in activities:
        if a.get("activity_sub_type") != _SWEEP_ACTIVITY_SUB_TYPE:
            continue
        # `net_amount` is the dollar interest credited; `qty` is the unit
        # count of the sweep instrument (SWEEPFDIC shares). They are equal
        # for the current FDIC sweep but `net_amount` is the canonical
        # currency-value field across all Alpaca activity records.
        raw = a.get("net_amount")
        if raw is None:
            continue
        total += Decimal(raw)
    return total


def _format_money(value: Decimal) -> str:
    return str(value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def _format_apy(value: Decimal) -> str:
    return str(value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP))


def _apy_from_tiers(tiers_resp: dict[str, Any] | None) -> str:
    """Find the configured APR tier and return its rate as a decimal string.

    Returns "0.0000" if the tier is missing — preferable to surfacing a stale
    rate after Alpaca renames or removes a tier in their console.
    """
    zero = _format_apy(Decimal("0"))
    target = settings.alpaca_apr_tier_name
    if not target:
        logger.warning("cash_interest_apr_tier_name_unconfigured")
        return zero
    if not tiers_resp:
        return zero
    tiers = tiers_resp.get("apr_tiers", [])
    for tier in tiers:
        if tier.get("name") != target:
            continue
        bps = tier.get("account_rate_bps")
        if bps is None:
            logger.warning(
                "cash_interest_apr_tier_missing_bps",
                configured_name=target,
            )
            return zero
        return _format_apy(Decimal(bps) / Decimal(10000))
    logger.warning(
        "cash_interest_apr_tier_not_found",
        configured_name=target,
        available=[t.get("name") for t in tiers],
    )
    sentry_sdk.capture_message(
        "cash_interest_apr_tier_not_found",
        level="warning",
    )
    return zero
