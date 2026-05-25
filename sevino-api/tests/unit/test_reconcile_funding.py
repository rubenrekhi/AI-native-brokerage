"""Unit tests for the hourly funding reconciliation task."""

import uuid
from unittest.mock import AsyncMock, MagicMock

from app.config import settings
from app.repositories.ach_relationship import (
    STATUS_APPROVED,
    STATUS_CANCELED,
    STATUS_QUEUED,
)
from app.repositories.brokerage_account import STATUS_ACTIVE
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.tasks.reconcile_funding import reconcile_funding


def _patch_session(monkeypatch) -> AsyncMock:
    session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.tasks.reconcile_funding.async_session", lambda: cm
    )
    return session


def _rel(
    *,
    alpaca_relationship_id: str,
    status: str,
    alpaca_account_id: str = "acct-1",
    account_status: str = STATUS_ACTIVE,
) -> MagicMock:
    """Build a fake AchRelationship loaded with its brokerage_account."""
    brokerage = MagicMock()
    brokerage.alpaca_account_id = alpaca_account_id
    brokerage.account_status = account_status

    rel = MagicMock()
    rel.id = uuid.uuid4()
    rel.user_id = uuid.uuid4()
    rel.alpaca_relationship_id = alpaca_relationship_id
    rel.status = status
    rel.brokerage_account = brokerage
    return rel


def _patch_repo(monkeypatch, rels: list) -> None:
    async def fake_list(db):
        return rels

    monkeypatch.setattr(
        "app.tasks.reconcile_funding.AchRelationshipRepository.list_all_non_canceled",
        fake_list,
    )


def _ctx(alpaca: MagicMock) -> dict:
    return {"alpaca": alpaca}


async def test_pr_preview_short_circuits(monkeypatch):
    """PR preview envs must not reconcile — they spin up against shared
    sandbox state and would generate spurious drift logs."""
    monkeypatch.setattr(settings, "railway_environment_name", "sevino-pr-42")
    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock()

    result = await reconcile_funding(_ctx(alpaca))

    assert result == {"status": "skipped", "reason": "pr-preview"}
    alpaca.list_ach_relationships.assert_not_called()


async def test_no_drift_when_all_statuses_match(monkeypatch):
    monkeypatch.setattr(settings, "railway_environment_name", "")
    session = _patch_session(monkeypatch)
    rel = _rel(alpaca_relationship_id="ach-1", status=STATUS_APPROVED)
    _patch_repo(monkeypatch, [rel])

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock(
        return_value=[{"id": "ach-1", "status": STATUS_APPROVED}]
    )

    result = await reconcile_funding(_ctx(alpaca))

    assert result["status"] == "ok"
    assert result["checked"] == 1
    assert result["drifted"] == 0
    assert result["canceled_server_side"] == 0
    assert result["errored_accounts"] == 0
    assert rel.status == STATUS_APPROVED
    session.commit.assert_awaited_once()


async def test_status_change_updates_local_and_emits_drift(monkeypatch):
    """QUEUED → APPROVED at Alpaca should flip local and log a drift event."""
    monkeypatch.setattr(settings, "railway_environment_name", "")
    _patch_session(monkeypatch)
    rel = _rel(alpaca_relationship_id="ach-1", status=STATUS_QUEUED)
    _patch_repo(monkeypatch, [rel])

    drift_logs: list[dict] = []
    real_logger = __import__(
        "app.tasks.reconcile_funding", fromlist=["logger"]
    ).logger

    def fake_info(event, **kwargs):
        if event == "funding_reconcile_drift":
            drift_logs.append(kwargs)

    monkeypatch.setattr(real_logger, "info", fake_info)

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock(
        return_value=[{"id": "ach-1", "status": STATUS_APPROVED}]
    )

    result = await reconcile_funding(_ctx(alpaca))

    assert result["drifted"] == 1
    assert result["canceled_server_side"] == 0
    assert rel.status == STATUS_APPROVED
    assert len(drift_logs) == 1
    assert drift_logs[0]["kind"] == "status_change"
    assert drift_logs[0]["status_from"] == STATUS_QUEUED
    assert drift_logs[0]["status_to"] == STATUS_APPROVED


async def test_server_side_cancellation_marks_canceled(monkeypatch):
    """Row exists locally but is absent from Alpaca's response → mark CANCELED
    and emit drift with kind=server_side_cancellation. This is the
    ops-observability case the cron exists for."""
    monkeypatch.setattr(settings, "railway_environment_name", "")
    _patch_session(monkeypatch)
    rel = _rel(alpaca_relationship_id="ach-gone", status=STATUS_APPROVED)
    _patch_repo(monkeypatch, [rel])

    drift_logs: list[dict] = []
    real_logger = __import__(
        "app.tasks.reconcile_funding", fromlist=["logger"]
    ).logger

    def fake_info(event, **kwargs):
        if event == "funding_reconcile_drift":
            drift_logs.append(kwargs)

    monkeypatch.setattr(real_logger, "info", fake_info)

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock(return_value=[])

    result = await reconcile_funding(_ctx(alpaca))

    assert result["canceled_server_side"] == 1
    assert result["drifted"] == 0
    assert rel.status == STATUS_CANCELED
    assert len(drift_logs) == 1
    assert drift_logs[0]["kind"] == "server_side_cancellation"
    assert drift_logs[0]["status_from"] == STATUS_APPROVED
    assert drift_logs[0]["status_to"] == STATUS_CANCELED


async def test_alpaca_error_on_one_account_isolated_from_others(monkeypatch):
    """One bad account must not abort the sweep — other accounts still
    reconcile, and the failed account is counted in errored_accounts."""
    monkeypatch.setattr(settings, "railway_environment_name", "")
    _patch_session(monkeypatch)

    bad_rel = _rel(
        alpaca_relationship_id="ach-bad",
        status=STATUS_QUEUED,
        alpaca_account_id="acct-bad",
    )
    good_rel = _rel(
        alpaca_relationship_id="ach-good",
        status=STATUS_QUEUED,
        alpaca_account_id="acct-good",
    )
    _patch_repo(monkeypatch, [bad_rel, good_rel])

    async def fake_list(account_id):
        if account_id == "acct-bad":
            raise AlpacaBrokerUnavailableError("connection refused")
        return [{"id": "ach-good", "status": STATUS_APPROVED}]

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock(side_effect=fake_list)

    result = await reconcile_funding(_ctx(alpaca))

    assert result["errored_accounts"] == 1
    assert result["checked"] == 1
    assert result["drifted"] == 1
    assert bad_rel.status == STATUS_QUEUED
    assert good_rel.status == STATUS_APPROVED


async def test_alpaca_4xx_on_account_counts_as_error_not_crash(monkeypatch):
    """A 4xx from Alpaca (account dropped, bad permissions) should be caught
    the same as a network error — log + skip, don't propagate."""
    monkeypatch.setattr(settings, "railway_environment_name", "")
    _patch_session(monkeypatch)
    rel = _rel(alpaca_relationship_id="ach-1", status=STATUS_QUEUED)
    _patch_repo(monkeypatch, [rel])

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock(
        side_effect=AlpacaBrokerError(status_code=403, message="forbidden")
    )

    result = await reconcile_funding(_ctx(alpaca))

    assert result["errored_accounts"] == 1
    assert result["checked"] == 0
    assert rel.status == STATUS_QUEUED


async def test_inactive_brokerage_account_is_skipped(monkeypatch):
    """If a row's brokerage account isn't ACTIVE (closed, suspended), don't
    call Alpaca for it — the upstream endpoint would 4xx anyway."""
    monkeypatch.setattr(settings, "railway_environment_name", "")
    _patch_session(monkeypatch)
    rel = _rel(
        alpaca_relationship_id="ach-1",
        status=STATUS_QUEUED,
        account_status="SUBMITTED",
    )
    _patch_repo(monkeypatch, [rel])

    alpaca = MagicMock()
    alpaca.list_ach_relationships = AsyncMock()

    result = await reconcile_funding(_ctx(alpaca))

    assert result["checked"] == 0
    assert result["errored_accounts"] == 0
    alpaca.list_ach_relationships.assert_not_called()
