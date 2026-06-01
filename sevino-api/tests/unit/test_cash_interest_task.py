"""Unit tests for the FDIC sweep enrollment ARQ task (SEV-655).

The task is exercised in isolation: ``async_session`` is patched to yield a
mock session, ``BrokerageAccountRepository.get_by_id`` is stubbed, and the
Alpaca client is an ``AsyncMock`` off ``ctx``.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from arq import Retry

from app.config import settings
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.tasks.cash_interest import (
    ENROLL_CASH_INTEREST_MAX_TRIES,
    enroll_cash_interest,
)

ACCOUNT_ID = uuid.uuid4()
ALPACA_ACCOUNT_ID = "alpaca_acc_42"


def _patch_session(monkeypatch) -> AsyncMock:
    session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr("app.tasks.cash_interest.async_session", lambda: cm)
    return session


def _patch_account(monkeypatch, account) -> AsyncMock:
    get = AsyncMock(return_value=account)
    monkeypatch.setattr(
        "app.tasks.cash_interest.BrokerageAccountRepository.get_by_id", get
    )
    return get


def _account(sweep_status: str | None = "PENDING_CHANGE") -> MagicMock:
    acct = MagicMock()
    acct.id = ACCOUNT_ID
    acct.alpaca_account_id = ALPACA_ACCOUNT_ID
    acct.sweep_status = sweep_status
    return acct


@pytest.fixture
def alpaca() -> AsyncMock:
    svc = AsyncMock()
    svc.assign_apr_tier = AsyncMock(return_value=None)
    return svc


@pytest.fixture(autouse=True)
def configured_tier(monkeypatch):
    monkeypatch.setattr(settings, "alpaca_apr_tier_name", "standard")


def _ctx(alpaca, job_try: int = 1) -> dict:
    return {"alpaca": alpaca, "job_try": job_try}


class TestHappyPath:
    async def test_assigns_tier_and_leaves_sweep_status(
        self, monkeypatch, alpaca
    ):
        session = _patch_session(monkeypatch)
        account = _account(sweep_status="PENDING_CHANGE")
        _patch_account(monkeypatch, account)

        await enroll_cash_interest(_ctx(alpaca), str(ACCOUNT_ID))

        alpaca.assign_apr_tier.assert_awaited_once_with(
            ALPACA_ACCOUNT_ID, "standard"
        )
        # Success must NOT touch sweep_status — it stays PENDING_CHANGE until
        # the Alpaca cash_interest SSE event flips it to ACTIVE.
        assert account.sweep_status == "PENDING_CHANGE"
        session.commit.assert_not_awaited()


class TestEarlyReturns:
    async def test_missing_tier_name_returns_early(
        self, monkeypatch, alpaca
    ):
        monkeypatch.setattr(settings, "alpaca_apr_tier_name", "")
        get = _patch_account(monkeypatch, _account())

        await enroll_cash_interest(_ctx(alpaca), str(ACCOUNT_ID))

        # Returns before loading the account or touching Alpaca.
        get.assert_not_awaited()
        alpaca.assign_apr_tier.assert_not_awaited()

    async def test_missing_account_returns_silently(
        self, monkeypatch, alpaca
    ):
        _patch_session(monkeypatch)
        _patch_account(monkeypatch, None)

        await enroll_cash_interest(_ctx(alpaca), str(ACCOUNT_ID))

        alpaca.assign_apr_tier.assert_not_awaited()


class TestFailureRetries:
    @pytest.mark.parametrize(
        "job_try,expected_defer_ms", [(1, 2000), (2, 4000)]
    )
    async def test_error_sets_inactive_and_retries_with_backoff(
        self, monkeypatch, alpaca, job_try, expected_defer_ms
    ):
        session = _patch_session(monkeypatch)
        account = _account(sweep_status="PENDING_CHANGE")
        _patch_account(monkeypatch, account)
        alpaca.assign_apr_tier.side_effect = AlpacaBrokerError(503, "down")
        capture = MagicMock()
        monkeypatch.setattr(
            "app.tasks.cash_interest.sentry_sdk.capture_message", capture
        )

        with pytest.raises(Retry) as exc_info:
            await enroll_cash_interest(
                _ctx(alpaca, job_try=job_try), str(ACCOUNT_ID)
            )

        assert account.sweep_status == "INACTIVE"
        session.commit.assert_awaited_once()
        # Exponential backoff: 2s, 4s, ...
        assert exc_info.value.defer_score == expected_defer_ms
        # Sentry is reserved for the final exhausted attempt.
        capture.assert_not_called()

    async def test_unavailable_error_also_retries(self, monkeypatch, alpaca):
        """Transport failures (``AlpacaBrokerUnavailableError``, a peer of
        ``AlpacaBrokerError``) are exactly the transient kind worth retrying."""
        session = _patch_session(monkeypatch)
        account = _account(sweep_status="PENDING_CHANGE")
        _patch_account(monkeypatch, account)
        alpaca.assign_apr_tier.side_effect = AlpacaBrokerUnavailableError(
            "connection refused"
        )

        with pytest.raises(Retry):
            await enroll_cash_interest(_ctx(alpaca, job_try=1), str(ACCOUNT_ID))

        assert account.sweep_status == "INACTIVE"
        session.commit.assert_awaited_once()

    async def test_final_attempt_captures_sentry_and_reraises(
        self, monkeypatch, alpaca
    ):
        session = _patch_session(monkeypatch)
        account = _account(sweep_status="PENDING_CHANGE")
        _patch_account(monkeypatch, account)
        alpaca.assign_apr_tier.side_effect = AlpacaBrokerError(503, "down")
        capture = MagicMock()
        monkeypatch.setattr(
            "app.tasks.cash_interest.sentry_sdk.capture_message", capture
        )

        # Last allowed attempt: re-raise the original error (terminal failure
        # in ARQ) rather than Retry, and surface one Sentry event.
        with pytest.raises(AlpacaBrokerError):
            await enroll_cash_interest(
                _ctx(alpaca, job_try=ENROLL_CASH_INTEREST_MAX_TRIES),
                str(ACCOUNT_ID),
            )

        assert account.sweep_status == "INACTIVE"
        session.commit.assert_awaited_once()
        capture.assert_called_once()
        assert capture.call_args.kwargs.get("level") == "error"
