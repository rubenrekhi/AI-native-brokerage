import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.account_status import apply_account_status_change


@pytest.fixture
def session():
    return AsyncMock()


def _account(status: str, kyc_results=None):
    acct = MagicMock()
    acct.id = uuid.uuid4()
    acct.account_status = status
    acct.kyc_results = kyc_results
    return acct


async def test_no_matching_account_is_noop(session, monkeypatch):
    get = AsyncMock(return_value=None)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )

    await apply_account_status_change(
        session, alpaca_account_id="unknown", new_status="ACTIVE"
    )

    get.assert_awaited_once()
    update.assert_not_awaited()


async def test_same_status_skips_update(session, monkeypatch):
    """Replays of already-applied events must not re-trigger side effects."""
    get = AsyncMock(return_value=_account("ACTIVE"))
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )

    update.assert_not_awaited()


async def test_active_transition_sets_activated_at_from_event_time(
    session, monkeypatch
):
    account = _account("APPROVED")
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
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="REJECTED"
    )

    update.assert_awaited_once_with(session, account.id, "REJECTED")


async def test_kyc_results_forwarded_when_present(session, monkeypatch):
    account = _account("SUBMITTED")
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )
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
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )

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
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )
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
    get = AsyncMock(return_value=account)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.get_by_alpaca_account_id",
        get,
    )
    monkeypatch.setattr(
        "app.services.account_status.BrokerageAccountRepository.update_status",
        update,
    )

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

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="REJECTED"
    )

    update.assert_awaited_once()
    profile_update.assert_not_awaited()


async def test_active_replay_is_noop_for_profile_flag(session, monkeypatch):
    """A replay of an already-ACTIVE event (same status, no kyc delta) must
    short-circuit before the profile flip — no redundant writes."""
    account = _account("ACTIVE")
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

    await apply_account_status_change(
        session, alpaca_account_id="abc", new_status="ACTIVE"
    )

    update.assert_not_awaited()
    profile_update.assert_not_awaited()
