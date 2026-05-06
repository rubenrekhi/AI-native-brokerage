"""Unit tests for CashInterestService.

Service is exercised in isolation: BrokerageAccountRepository is mocked, the
Alpaca client is a stub AsyncMock. Integration coverage (real router, error
mapping) lives in tests/integration/test_brokerage_routes.py.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.exceptions import NotFoundError
from app.services.alpaca_broker import AlpacaBrokerError
from app.services.cash_interest import CashInterestService

USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ALPACA_ACCOUNT_ID = "alpaca_acc_42"
ENROLLED_AT = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def alpaca() -> AsyncMock:
    svc = AsyncMock()
    svc.get_trading_account.return_value = {
        "cash": "2412.08",
        "buying_power": "2412.08",
        "pending_transfer_in": "100.00",
    }
    svc.get_eod_cash_interest.return_value = []
    svc.get_apr_tiers.return_value = {"apr_tiers": []}
    svc.get_interest_activities.return_value = []
    return svc


def _make_brokerage(
    *,
    sweep_status: str | None = "ACTIVE",
    sweep_enrolled_at: datetime | None = ENROLLED_AT,
    account_status: str = "ACTIVE",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        alpaca_account_id=ALPACA_ACCOUNT_ID,
        account_status=account_status,
        sweep_status=sweep_status,
        sweep_enrolled_at=sweep_enrolled_at,
    )


@pytest.fixture
def patch_brokerage(mocker):
    def _patch(brokerage):
        return mocker.patch(
            "app.services.brokerage.BrokerageAccountRepository.get_by_user_id",
            new_callable=AsyncMock,
            return_value=brokerage,
        )

    return _patch


@pytest.fixture
def configured_apr_tier(monkeypatch):
    """Pin the APR tier name so `_apy_from_tiers` always knows what to look for.

    The underlying setting defaults to "" (no tier configured), which would
    make every test pick the unconfigured branch. Tests that need a real
    lookup need the name to match a tier in the mocked response.
    """
    monkeypatch.setattr(settings, "alpaca_apr_tier_name", "standard")


# ---------------------------------------------------------------------------
# Brokerage gate
# ---------------------------------------------------------------------------


class TestBrokerageGate:
    async def test_missing_brokerage_raises_not_found(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(None)

        with pytest.raises(NotFoundError):
            await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        alpaca.get_trading_account.assert_not_called()

    async def test_closed_brokerage_raises_not_found(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(_make_brokerage(account_status="ACCOUNT_CLOSED"))

        with pytest.raises(NotFoundError):
            await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        alpaca.get_trading_account.assert_not_called()


# ---------------------------------------------------------------------------
# Active sweep — full aggregation
# ---------------------------------------------------------------------------


class TestActiveSweep:
    async def test_populates_all_fields_from_alpaca(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.return_value = {
            "apr_tiers": [
                {"name": "standard", "account_rate_bps": 425},
                {"name": "premium", "account_rate_bps": 500},
            ]
        }
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1).isoformat()
        alpaca.get_eod_cash_interest.return_value = [
            {"date": first_of_month, "account_accrued_interest": "1.50"},
            {"date": first_of_month, "account_accrued_interest": "2.00"},
            {"date": first_of_month, "account_accrued_interest": "2.93"},
        ]
        alpaca.get_interest_activities.return_value = [
            {"activity_sub_type": "SWP", "net_amount": "20.00", "qty": "20.00"},
            {"activity_sub_type": "SWP", "net_amount": "15.44", "qty": "15.44"},
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.balance == "2412.08"
        assert result.buying_power == "2412.08"
        assert result.pending_deposits == "100.00"
        assert result.apy == "0.0425"
        assert result.this_month_earned == "6.43"
        assert result.days_accrued == 3
        # Per spec: lifetime = realized SWP payouts (35.44) + current month
        # accrual (6.43). Resets to ~realized on payout day so the total
        # stays roughly monotonic across the SWP boundary.
        assert result.lifetime_earned == "41.87"
        assert result.lifetime_since == ENROLLED_AT
        assert result.interest_paid_out == "monthly"
        assert result.fdic_insured_limit == "2500000"
        assert result.sweep_status == "ACTIVE"

    async def test_eod_records_summed_to_two_decimals(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1).isoformat()
        alpaca.get_eod_cash_interest.return_value = [
            {"date": first_of_month, "account_accrued_interest": "1.1806"},
            {"date": first_of_month, "account_accrued_interest": "1.1809"},
            {"date": first_of_month, "account_accrued_interest": "1.1812"},
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        # 3.5427 quantized to 2 places (HALF_UP) → 3.54
        assert result.this_month_earned == "3.54"
        assert result.days_accrued == 3

    async def test_swp_uses_net_amount_not_qty(
        self, db, alpaca, patch_brokerage
    ):
        # `net_amount` is dollars; `qty` is sweep-instrument shares (currently
        # SWEEPFDIC at $1/share, so values match for this product). Pinning
        # to net_amount future-proofs against any sweep-instrument change.
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_interest_activities.return_value = [
            {"activity_sub_type": "SWP", "net_amount": "10.00", "qty": "9999"},
            {"activity_sub_type": "SWP", "net_amount": "5.00", "qty": "9999"},
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        # Realized 15.00 + this_month_earned 0 (no EOD records).
        assert result.lifetime_earned == "15.00"

    async def test_only_swp_activities_counted_toward_lifetime(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_interest_activities.return_value = [
            {"activity_sub_type": "SWP", "net_amount": "10.00"},
            {"activity_sub_type": "MGN", "net_amount": "999.00"},
            {"activity_sub_type": "SWP", "net_amount": "5.00"},
            {"activity_sub_type": "OTHER", "net_amount": "777.00"},
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.lifetime_earned == "15.00"

    async def test_lifetime_since_null_when_not_enrolled(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(
            _make_brokerage(sweep_status="ACTIVE", sweep_enrolled_at=None)
        )

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.lifetime_since is None


# ---------------------------------------------------------------------------
# EOD wire-format and boundary handling
# ---------------------------------------------------------------------------


class TestEodBoundary:
    async def test_eod_call_passes_month_window(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))

        await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        alpaca.get_eod_cash_interest.assert_awaited_once()
        kwargs = alpaca.get_eod_cash_interest.await_args.kwargs
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1)
        # `after` is the day before first-of-month so a record dated the 1st
        # is included regardless of whether Alpaca treats `after` as exclusive.
        assert kwargs["after"] == (first_of_month - timedelta(days=1)).isoformat()
        assert kwargs["before"] == today.isoformat()
        assert kwargs["account_id"] == ALPACA_ACCOUNT_ID

    async def test_records_missing_date_field_kept_and_logged(
        self, db, alpaca, patch_brokerage, caplog
    ):
        # Schema drift: keep the record (request was scoped to the month)
        # but log so the silent inclusion is observable in ops.
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_eod_cash_interest.return_value = [
            {"account_accrued_interest": "1.00"},  # no `date`
        ]

        with caplog.at_level("WARNING", logger="app.services.cash_interest"):
            result = await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        assert result.this_month_earned == "1.00"
        assert result.days_accrued == 1
        assert any(
            "cash_interest_eod_record_missing_date" in r.getMessage()
            for r in caplog.records
        )

    async def test_records_dated_before_first_of_month_filtered_out(
        self, db, alpaca, patch_brokerage
    ):
        # If Alpaca returns a stray record for the day before the 1st (which
        # can happen when `after` is inclusive), it must not contribute to
        # this_month_earned or days_accrued.
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1)
        prior_day = (first_of_month - timedelta(days=1)).isoformat()
        in_month = first_of_month.isoformat()
        alpaca.get_eod_cash_interest.return_value = [
            {"date": prior_day, "account_accrued_interest": "99.00"},
            {"date": in_month, "account_accrued_interest": "1.00"},
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.this_month_earned == "1.00"
        assert result.days_accrued == 1


# ---------------------------------------------------------------------------
# APR tier lookup
# ---------------------------------------------------------------------------


class TestAprTierLookup:
    async def test_tier_not_found_returns_zero(
        self, db, alpaca, patch_brokerage, configured_apr_tier, caplog
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "premium", "account_rate_bps": 500}]
        }

        with caplog.at_level("WARNING", logger="app.services.cash_interest"):
            result = await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        assert result.apy == "0.0000"
        assert any(
            "cash_interest_apr_tier_not_found" in r.getMessage()
            for r in caplog.records
        )

    async def test_unconfigured_tier_name_skips_call_logs_zero(
        self, db, alpaca, patch_brokerage, monkeypatch, caplog
    ):
        # Default "" — tier name not configured. The Alpaca call is skipped
        # entirely (no point looking up a tier we won't match) and the apy
        # field reports zero with a warning so ops can spot the misconfig.
        monkeypatch.setattr(settings, "alpaca_apr_tier_name", "")
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))

        with caplog.at_level("WARNING", logger="app.services.cash_interest"):
            result = await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        assert result.apy == "0.0000"
        alpaca.get_apr_tiers.assert_not_called()
        assert any(
            "cash_interest_apr_tier_name_unconfigured" in r.getMessage()
            for r in caplog.records
        )

    async def test_tier_missing_bps_returns_zero_and_logs(
        self, db, alpaca, patch_brokerage, configured_apr_tier, caplog
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "standard"}]  # no account_rate_bps
        }

        with caplog.at_level("WARNING", logger="app.services.cash_interest"):
            result = await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )

        assert result.apy == "0.0000"
        assert any(
            "cash_interest_apr_tier_missing_bps" in r.getMessage()
            for r in caplog.records
        )

    async def test_empty_tiers_returns_zero(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.return_value = {"apr_tiers": []}

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.apy == "0.0000"

    async def test_bps_quantized_to_four_decimals(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "standard", "account_rate_bps": 500}]
        }

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        # 500 bps → 0.05 → quantized to 4 places → "0.0500"
        assert result.apy == "0.0500"


# ---------------------------------------------------------------------------
# Non-active sweep — short-circuit
# ---------------------------------------------------------------------------


class TestInactiveSweep:
    @pytest.mark.parametrize(
        "sweep_status", [None, "INACTIVE", "PENDING_CHANGE"]
    )
    async def test_returns_zeros_and_skips_interest_calls(
        self, db, alpaca, patch_brokerage, sweep_status
    ):
        patch_brokerage(_make_brokerage(sweep_status=sweep_status))

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        # Trading account still queried for balance/buying_power.
        alpaca.get_trading_account.assert_awaited_once_with(ALPACA_ACCOUNT_ID)
        # Interest endpoints skipped entirely — no point hitting them when
        # there's no sweep enrollment to report on.
        alpaca.get_eod_cash_interest.assert_not_called()
        alpaca.get_apr_tiers.assert_not_called()
        alpaca.get_interest_activities.assert_not_called()

        assert result.balance == "2412.08"
        assert result.buying_power == "2412.08"
        assert result.pending_deposits == "100.00"
        assert result.apy == "0.0000"
        assert result.this_month_earned == "0.00"
        assert result.days_accrued == 0
        assert result.lifetime_earned == "0.00"
        assert result.sweep_status == sweep_status


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    async def test_eod_failure_zeros_accrual_but_keeps_balance(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_eod_cash_interest.side_effect = AlpacaBrokerError(
            status_code=500, message="reporting offline"
        )
        alpaca.get_apr_tiers.return_value = {
            "apr_tiers": [{"name": "standard", "account_rate_bps": 425}]
        }
        alpaca.get_interest_activities.return_value = [
            {"activity_sub_type": "SWP", "net_amount": "10.00"}
        ]

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.balance == "2412.08"
        assert result.buying_power == "2412.08"
        assert result.this_month_earned == "0.00"
        assert result.days_accrued == 0
        # Realized SWP still surfaces independently of EOD.
        assert result.lifetime_earned == "10.00"
        assert result.apy == "0.0425"

    async def test_activities_failure_zeros_lifetime(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        today = datetime.now(timezone.utc).date()
        first_of_month = today.replace(day=1).isoformat()
        alpaca.get_eod_cash_interest.return_value = [
            {"date": first_of_month, "account_accrued_interest": "1.00"},
            {"date": first_of_month, "account_accrued_interest": "1.00"},
        ]
        alpaca.get_interest_activities.side_effect = AlpacaBrokerError(
            status_code=500, message="activities offline"
        )

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.this_month_earned == "2.00"
        assert result.days_accrued == 2
        # Realized SWP degrades to 0 when activities fail; current-month
        # accrual still surfaces, so lifetime falls back to this_month_earned.
        assert result.lifetime_earned == "2.00"

    async def test_apr_tiers_failure_zeros_apy(
        self, db, alpaca, patch_brokerage, configured_apr_tier
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_apr_tiers.side_effect = AlpacaBrokerError(
            status_code=500, message="tiers offline"
        )

        result = await CashInterestService.get_cash_interest(
            db, alpaca=alpaca, user_id=USER_ID
        )

        assert result.apy == "0.0000"

    async def test_trading_account_failure_propagates(
        self, db, alpaca, patch_brokerage
    ):
        patch_brokerage(_make_brokerage(sweep_status="ACTIVE"))
        alpaca.get_trading_account.side_effect = AlpacaBrokerError(
            status_code=502, message="bad gateway"
        )

        with pytest.raises(AlpacaBrokerError):
            await CashInterestService.get_cash_interest(
                db, alpaca=alpaca, user_id=USER_ID
            )
