import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.account_status import apply_account_status_change
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)


@pytest.fixture
def session():
    return AsyncMock()


def _account(status: str, kyc_results=None):
    acct = MagicMock()
    acct.id = uuid.uuid4()
    acct.account_status = status
    acct.kyc_results = kyc_results
    return acct


def _patch_repos(monkeypatch, account):
    """Wire up the repository mocks the service touches."""
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    profile_update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )
    monkeypatch.setattr(
        "app.services.account_status.UserProfileRepository.update_fields",
        profile_update,
    )
    return get, update, profile_update


async def test_no_matching_account_is_noop(session, monkeypatch):
    get, update, _ = _patch_repos(monkeypatch, None)

    await apply_account_status_change(
        session, alpaca_account_id="unknown", new_status="ACTIVE"
    )

    get.assert_awaited_once()
    update.assert_not_awaited()


async def test_same_status_skips_update(session, monkeypatch):
    """Replays of already-applied events must not re-trigger side effects."""
    _, update, _ = _patch_repos(monkeypatch, _account("ACTIVE"))

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )

    update.assert_not_awaited()


async def test_active_transition_sets_activated_at_from_event_time(
    session, monkeypatch
):
    account = _account("APPROVED")
    _, update, _ = _patch_repos(monkeypatch, account)
    event_time = datetime(2023, 10, 13, 13, 34, 28, tzinfo=timezone.utc)

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="ACTIVE",
        event_time=event_time,
    )

    update.assert_awaited_once_with(
        session, account.id, "ACTIVE", activated_at=event_time
    )


async def test_active_transition_without_event_time_uses_now(session, monkeypatch):
    account = _account("APPROVED")
    _, update, _ = _patch_repos(monkeypatch, account)

    before = datetime.now(timezone.utc)
    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )
    after = datetime.now(timezone.utc)

    update.assert_awaited_once()
    kwargs = update.await_args.kwargs
    assert "activated_at" in kwargs
    assert before <= kwargs["activated_at"] <= after


async def test_rejected_transition_updates_status_without_activated_at(
    session, monkeypatch
):
    account = _account("SUBMITTED")
    _, update, _ = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="REJECTED"
    )

    update.assert_awaited_once_with(session, account.id, "REJECTED")


async def test_kyc_results_forwarded_when_present(session, monkeypatch):
    account = _account("SUBMITTED")
    _, update, _ = _patch_repos(monkeypatch, account)
    kyc = {"reject": ["OFAC hit"]}

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="REJECTED",
        kyc_results=kyc,
    )

    update.assert_awaited_once_with(
        session, account.id, "REJECTED", kyc_results=kyc
    )


async def test_kyc_results_omitted_when_none(session, monkeypatch):
    account = _account("SUBMITTED")
    _, update, _ = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="APPROVED",
        kyc_results=None,
    )

    kwargs = update.await_args.kwargs
    assert "kyc_results" not in kwargs


async def test_same_status_new_kyc_results_applies_kyc_update(
    session, monkeypatch
):
    """Alpaca's stream fires on kyc_results deltas alone (per the reference
    page: "Only the changed properties are included in the event payload").
    A same-status event with an updated kyc_results blob — e.g. a reviewer
    amending rejection notes — must be applied, not skipped."""
    account = _account("REJECTED", kyc_results={"reject": ["old reason"]})
    _, update, _ = _patch_repos(monkeypatch, account)
    new_kyc = {"reject": ["amended reason"]}

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="REJECTED",
        kyc_results=new_kyc,
    )

    update.assert_awaited_once_with(
        session, account.id, "REJECTED", kyc_results=new_kyc
    )


async def test_same_status_same_kyc_results_is_noop(session, monkeypatch):
    """Full replay (status + kyc_results both unchanged) must be a no-op."""
    same_kyc = {"reject": ["unchanged"]}
    account = _account("REJECTED", kyc_results=same_kyc)
    _, update, _ = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="REJECTED",
        kyc_results=same_kyc,
    )

    update.assert_not_awaited()


async def test_active_replay_with_new_kyc_does_not_overwrite_activated_at(
    session, monkeypatch
):
    """An already-ACTIVE account receiving a kyc_results-only event must
    NOT re-stamp activated_at — that field anchors the original activation
    moment and is user-visible. Only the *first* ACTIVE transition sets it."""
    account = _account("ACTIVE", kyc_results=None)
    _, update, profile_update = _patch_repos(monkeypatch, account)
    new_kyc = {"accept": ["CIP retry ok"]}

    await apply_account_status_change(
        session,
        alpaca_account_id="abc",
        new_status="ACTIVE",
        kyc_results=new_kyc,
        event_time=datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    )

    update.assert_awaited_once()
    kwargs = update.await_args.kwargs
    assert kwargs == {"kyc_results": new_kyc}
    assert "activated_at" not in kwargs
    # kyc-only replays on an already-ACTIVE account must NOT touch the
    # profile flag — the flip belongs to the first ACTIVE transition only.
    profile_update.assert_not_awaited()


async def test_active_transition_flips_onboarding_completed(session, monkeypatch):
    """First ACTIVE transition flips user_profile.onboarding_completed=True
    in the same transaction (SEV-327)."""
    user_id = uuid.uuid4()
    account = _account("APPROVED")
    account.user_id = user_id
    _, _, profile_update = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )

    profile_update.assert_awaited_once_with(
        session, user_id, onboarding_completed=True
    )


async def test_non_active_transition_does_not_flip_onboarding_completed(
    session, monkeypatch
):
    """REJECTED / APPROVAL_PENDING / etc. must never flip the profile flag."""
    account = _account("SUBMITTED")
    _, update, profile_update = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="REJECTED"
    )

    update.assert_awaited_once()
    profile_update.assert_not_awaited()


async def test_active_replay_is_noop_for_profile_flag(session, monkeypatch):
    """A replay of an already-ACTIVE event (same status, no kyc delta) must
    short-circuit before the profile flip — no redundant writes."""
    account = _account("ACTIVE")
    _, update, profile_update = _patch_repos(monkeypatch, account)

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )

    update.assert_not_awaited()
    profile_update.assert_not_awaited()


class TestSweepEnrollmentOnActive:
    """SEV-318: first ACTIVE transition PATCHes Alpaca to assign the
    configured FDIC sweep tier, recording the outcome on the brokerage
    account row."""

    async def test_active_transition_patches_alpaca_with_configured_tier(
        self, session, monkeypatch
    ):
        account = _account("APPROVED")
        _, update, _ = _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock(return_value={})
        event_time = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            event_time=event_time,
            alpaca=alpaca,
        )

        alpaca.update_account.assert_awaited_once_with(
            "abc",
            {"cash_interest": {"USD": {"apr_tier_name": "standard"}}},
        )
        kwargs = update.await_args.kwargs
        assert kwargs["sweep_status"] == "PENDING_CHANGE"
        assert kwargs["sweep_enrolled_at"] == event_time
        assert kwargs["activated_at"] == event_time

    async def test_alpaca_error_marks_sweep_inactive_but_still_activates(
        self, session, monkeypatch
    ):
        account = _account("APPROVED")
        _, update, profile_update = _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock(
            side_effect=AlpacaBrokerError(503, "upstream down")
        )

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            alpaca=alpaca,
        )

        kwargs = update.await_args.kwargs
        assert kwargs["sweep_status"] == "INACTIVE"
        assert "sweep_enrolled_at" not in kwargs
        # The account still goes ACTIVE and onboarding still completes —
        # enrollment failures must not block account activation.
        assert "activated_at" in kwargs
        profile_update.assert_awaited_once()

    async def test_alpaca_unavailable_marks_sweep_inactive_but_still_activates(
        self, session, monkeypatch
    ):
        """Transport-level failures (connection refused, DNS, timeout) raise
        ``AlpacaBrokerUnavailableError`` — a peer of ``AlpacaBrokerError``,
        not a subclass. If we don't catch both, the exception escapes
        ``apply_account_status_change`` and ``BaseSSEListener`` rolls back
        the entire transaction, stalling activation on every transient
        Alpaca network blip."""
        account = _account("APPROVED")
        _, update, profile_update = _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock(
            side_effect=AlpacaBrokerUnavailableError("connection refused")
        )

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            alpaca=alpaca,
        )

        kwargs = update.await_args.kwargs
        assert kwargs["sweep_status"] == "INACTIVE"
        assert "sweep_enrolled_at" not in kwargs
        assert "activated_at" in kwargs
        profile_update.assert_awaited_once()

    async def test_skips_enrollment_when_tier_name_unconfigured(
        self, session, monkeypatch
    ):
        account = _account("APPROVED")
        _, update, _ = _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name", ""
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock()

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            alpaca=alpaca,
        )

        alpaca.update_account.assert_not_awaited()
        kwargs = update.await_args.kwargs
        assert "sweep_status" not in kwargs
        assert "sweep_enrolled_at" not in kwargs

    async def test_skips_enrollment_when_alpaca_is_none(
        self, session, monkeypatch
    ):
        """The ``alpaca`` parameter is optional; when omitted, enrollment
        must silently skip rather than NoneType-explode."""
        account = _account("APPROVED")
        _, update, _ = _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            alpaca=None,
        )

        kwargs = update.await_args.kwargs
        assert "sweep_status" not in kwargs
        assert "sweep_enrolled_at" not in kwargs

    async def test_non_active_transition_does_not_enroll(
        self, session, monkeypatch
    ):
        account = _account("SUBMITTED")
        _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock()

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="REJECTED",
            alpaca=alpaca,
        )

        alpaca.update_account.assert_not_awaited()

    async def test_active_replay_with_kyc_delta_does_not_re_enroll(
        self, session, monkeypatch
    ):
        """A kyc_results-only event on an already-ACTIVE account must not
        re-trigger enrollment — only the *first* ACTIVE transition does."""
        account = _account("ACTIVE", kyc_results=None)
        _patch_repos(monkeypatch, account)
        monkeypatch.setattr(
            "app.services.account_status.settings.alpaca_apr_tier_name",
            "standard",
        )
        alpaca = AsyncMock()
        alpaca.update_account = AsyncMock()

        await apply_account_status_change(
            session,
            alpaca_account_id="abc",
            new_status="ACTIVE",
            kyc_results={"accept": ["CIP retry ok"]},
            alpaca=alpaca,
        )

        alpaca.update_account.assert_not_awaited()
