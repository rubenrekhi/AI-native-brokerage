"""DB-backed tests for PendingActionRepository — the atomic-CAS safety
backbone of the HIL framework (docs/ai/hil-actions.md)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.exceptions import NotFoundError
from app.models.pending_action import PendingActionStatus
from app.repositories.conversation import ConversationRepository
from app.repositories.pending_action import PendingActionRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


async def _make_conversation(db, user_id: uuid.UUID) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await ConversationRepository.create_conversation(
        db, conversation_id=conversation_id, user_id=user_id
    )
    await db.flush()
    return conversation_id


async def _make_pending(
    db,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    expires_in_s: int = 300,
):
    now = datetime.now(timezone.utc)
    row = await PendingActionRepository.create(
        db,
        action_id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        agent_turn_id=None,
        tool_use_id="tu_1",
        action_type="transfer",
        payload={"amount": "10.00", "direction": "INCOMING"},
        preview={"action_id": "x"},
        expires_at=now + timedelta(seconds=expires_in_s),
    )
    await db.flush()
    return row


async def test_confirm_is_idempotent_only_first_wins(db_session, test_user):
    cid = await _make_conversation(db_session, test_user)
    row = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )

    first = await PendingActionRepository.confirm(
        db_session, action_id=row.id
    )
    assert first is not None
    assert first.status == PendingActionStatus.CONFIRMED
    assert first.confirmed_at is not None

    # Double-tap: the CAS guard rejects the second confirm.
    second = await PendingActionRepository.confirm(
        db_session, action_id=row.id
    )
    assert second is None


async def test_confirm_expired_returns_none(db_session, test_user):
    cid = await _make_conversation(db_session, test_user)
    row = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid, expires_in_s=-5
    )
    assert await PendingActionRepository.confirm(
        db_session, action_id=row.id
    ) is None


async def test_reject_transitions_pending_only(db_session, test_user):
    cid = await _make_conversation(db_session, test_user)
    row = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )
    rejected = await PendingActionRepository.reject(
        db_session, action_id=row.id
    )
    assert rejected is not None
    assert rejected.status == PendingActionStatus.REJECTED
    # Can't confirm a rejected action.
    assert await PendingActionRepository.confirm(
        db_session, action_id=row.id
    ) is None


async def test_supersede_sweep_marks_live_pending_only(
    db_session, test_user
):
    cid = await _make_conversation(db_session, test_user)
    live = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )
    confirmed = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )
    expired = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid, expires_in_s=-5
    )
    await PendingActionRepository.confirm(
        db_session, action_id=confirmed.id
    )

    count = await PendingActionRepository.supersede_pending_for_conversation(
        db_session, conversation_id=cid
    )
    # Only the live-pending row is superseded; confirmed + expired untouched.
    assert count == 1

    statuses = await PendingActionRepository.effective_statuses(
        db_session, action_ids=[live.id, confirmed.id, expired.id]
    )
    assert statuses[live.id] == PendingActionStatus.SUPERSEDED
    assert statuses[confirmed.id] == PendingActionStatus.CONFIRMED
    assert statuses[expired.id] == PendingActionStatus.EXPIRED


async def test_get_owned_rejects_wrong_user(
    db_session, test_user, make_extra_user
):
    cid = await _make_conversation(db_session, test_user)
    row = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )
    other = await make_extra_user()
    with pytest.raises(NotFoundError):
        await PendingActionRepository.get_owned(
            db_session,
            action_id=row.id,
            user_id=other,
            conversation_id=cid,
        )


async def test_mark_executed_records_result(db_session, test_user):
    cid = await _make_conversation(db_session, test_user)
    row = await _make_pending(
        db_session, user_id=test_user, conversation_id=cid
    )
    await PendingActionRepository.confirm(db_session, action_id=row.id)
    await PendingActionRepository.mark_executed(
        db_session, action_id=row.id, result={"transfer_id": "xfer_1"}
    )
    fetched = await PendingActionRepository.get_owned(
        db_session,
        action_id=row.id,
        user_id=test_user,
        conversation_id=cid,
    )
    assert fetched.status == PendingActionStatus.EXECUTED
    assert fetched.result == {"transfer_id": "xfer_1"}
    assert fetched.executed_at is not None


async def test_effective_statuses_empty_input(db_session):
    assert (
        await PendingActionRepository.effective_statuses(
            db_session, action_ids=[]
        )
        == {}
    )
