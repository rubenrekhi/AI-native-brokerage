"""Integration tests for the HIL confirm endpoint
``POST /v1/conversations/{id}/actions/{action_id}``.

Drives the reverse channel end to end against the real DB with a stub executor
registered for a test ``action_type``: confirm runs the executor, streams the
result into the conversation, and marks the row executed; reject acks; a
stale/expired/foreign action is refused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.actions import (
    ACTION_EXECUTORS,
    ActionContext,
    ActionResult,
    register_action_executor,
)
from app.ai.blocks import ConfirmationBlock, ConfirmationRow
from app.ai.runtime.db import get_db_factory, make_session_factory
from app.ai.transport.events import (
    BlockEnd,
    BlockStart,
    Event,
    TurnCompleted,
    TurnStarted,
    parse_wire_frame,
)
from app.auth import get_current_user
from app.main import app
from app.models.message import Message as MessageRow
from app.models.pending_action import PendingAction, PendingActionStatus
from app.repositories.conversation import ConversationRepository
from app.repositories.pending_action import PendingActionRepository
from tests.integration.conftest import (
    TEST_API_KEY,
    _pg_available_sync,
    insert_auth_user,
)

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

_TEST_ACTION_TYPE = "test_transfer"
_EXECUTOR_CALLS: list[tuple[dict[str, Any], ActionContext]] = []


async def _stub_executor(
    payload: dict[str, Any], ctx: ActionContext
) -> ActionResult:
    _EXECUTOR_CALLS.append((payload, ctx))
    return ActionResult(
        status="executed",
        result_block=ConfirmationBlock(
            block_id="res1",
            action_id="res",
            kind="transfer",
            title="Deposit submitted",
            rows=[ConfirmationRow(label="Amount", value="$10.00")],
            status="executed",
        ),
        summary={"transfer_id": "xfer_1", "status": "QUEUED"},
        narration="Your $10.00 deposit is on its way ✅",
    )


async def _consume_sse(
    client: AsyncClient, url: str, *, json: dict[str, Any]
) -> list[Event]:
    async with client.stream("POST", url, json=json) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith(
            "text/event-stream"
        )
        body = (await response.aread()).decode("utf-8")
    normalised = body.replace("\r\n", "\n")
    return [
        parse_wire_frame(frame)
        for frame in normalised.split("\n\n")
        if frame.strip()
    ]


class _Fixture:
    def __init__(self, *, user_id, conversation_id, action_id, engine):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.action_id = action_id
        self.engine = engine

    async def cleanup(self) -> None:
        async with AsyncSession(bind=self.engine) as c:
            await c.execute(
                text(
                    "DELETE FROM pending_actions WHERE conversation_id = :id"
                ),
                {"id": self.conversation_id},
            )
            await c.execute(
                text("DELETE FROM messages WHERE conversation_id = :id"),
                {"id": self.conversation_id},
            )
            await c.execute(
                text("DELETE FROM conversations WHERE id = :id"),
                {"id": self.conversation_id},
            )
            await c.execute(
                text("DELETE FROM user_profiles WHERE id = :id"),
                {"id": self.user_id},
            )
            await c.execute(
                text("DELETE FROM auth.users WHERE id = :id"),
                {"id": self.user_id},
            )
            await c.commit()


async def _seed(
    engine, *, expires_in_s: int = 300, status: str | None = None
) -> _Fixture:
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    action_id = uuid.uuid4()
    email = f"actions-{user_id}@test.local"
    async with AsyncSession(bind=engine, expire_on_commit=False) as setup:
        await insert_auth_user(setup, user_id=user_id, email=email)
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await PendingActionRepository.create(
            setup,
            action_id=action_id,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_turn_id=None,
            tool_use_id="tu_1",
            action_type=_TEST_ACTION_TYPE,
            payload={"amount": "10.00", "direction": "INCOMING"},
            preview={"action_id": str(action_id)},
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=expires_in_s),
        )
        if status is not None:
            await setup.execute(
                text(
                    "UPDATE pending_actions SET status = :s WHERE id = :id"
                ),
                {"s": status, "id": action_id},
            )
        await setup.commit()
    return _Fixture(
        user_id=user_id,
        conversation_id=conversation_id,
        action_id=action_id,
        engine=engine,
    )


@pytest.fixture(autouse=True)
def _register_executor():
    _EXECUTOR_CALLS.clear()
    if _TEST_ACTION_TYPE not in ACTION_EXECUTORS:
        register_action_executor(_TEST_ACTION_TYPE, _stub_executor)
    yield
    ACTION_EXECUTORS.pop(_TEST_ACTION_TYPE, None)
    _EXECUTOR_CALLS.clear()


@pytest.fixture
async def client(db_engine):
    db_factory = make_session_factory(db_engine)
    app.dependency_overrides[get_db_factory] = lambda: db_factory
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_db_factory, None)
    app.dependency_overrides.pop(get_current_user, None)


def _auth_as(user_id: uuid.UUID) -> None:
    app.dependency_overrides[get_current_user] = lambda: str(user_id)


def _url(fix: _Fixture) -> str:
    return (
        f"/v1/conversations/{fix.conversation_id}"
        f"/actions/{fix.action_id}"
    )


class TestConfirm:
    async def test_confirm_e2e(self, db_engine, client):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            events = await _consume_sse(
                client, _url(fix), json={"decision": "confirm"}
            )

            types = [type(e) for e in events]
            assert types[0] is TurnStarted
            assert types[-1] is TurnCompleted
            assert BlockStart in types and BlockEnd in types

            completed = events[-1]
            assert isinstance(completed, TurnCompleted)
            assert completed.terminal_state == "executed"

            # Executor ran with the server-persisted payload.
            assert len(_EXECUTOR_CALLS) == 1
            payload, _ctx = _EXECUTOR_CALLS[0]
            assert payload == {"amount": "10.00", "direction": "INCOMING"}

            # A confirmation result card was streamed.
            starts = [e for e in events if isinstance(e, BlockStart)]
            assert any(
                s.block.get("type") == "confirmation"
                and s.block.get("status") == "executed"
                for s in starts
            )

            async with AsyncSession(bind=db_engine) as q:
                row = (
                    await q.execute(
                        select(PendingAction).where(
                            PendingAction.id == fix.action_id
                        )
                    )
                ).scalar_one()
                assert row.status == PendingActionStatus.EXECUTED
                assert row.result == {
                    "transfer_id": "xfer_1",
                    "status": "QUEUED",
                }

                msgs = (
                    await q.execute(
                        select(MessageRow).where(
                            MessageRow.conversation_id == fix.conversation_id
                        )
                    )
                ).scalars().all()
                assert len(msgs) == 1
                assert msgs[0].role == "assistant"
                kinds = [b.get("type") for b in msgs[0].content_blocks]
                assert "text" in kinds and "confirmation" in kinds
        finally:
            await fix.cleanup()

    async def test_double_confirm_is_refused(self, db_engine, client):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            await _consume_sse(
                client, _url(fix), json={"decision": "confirm"}
            )
            resp = await client.post(_url(fix), json={"decision": "confirm"})
            assert resp.status_code == 409
            assert resp.json()["code"] == "ACTION_NOT_AVAILABLE"
        finally:
            await fix.cleanup()

    async def test_expired_confirm_is_refused(self, db_engine, client):
        fix = await _seed(db_engine, expires_in_s=-5)
        _auth_as(fix.user_id)
        try:
            resp = await client.post(_url(fix), json={"decision": "confirm"})
            assert resp.status_code == 409
            assert resp.json()["code"] == "ACTION_NOT_AVAILABLE"
            assert not _EXECUTOR_CALLS
        finally:
            await fix.cleanup()

    async def test_unknown_action_is_404(self, db_engine, client):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            bogus = (
                f"/v1/conversations/{fix.conversation_id}"
                f"/actions/{uuid.uuid4()}"
            )
            resp = await client.post(bogus, json={"decision": "confirm"})
            assert resp.status_code == 404
        finally:
            await fix.cleanup()


class TestReject:
    async def test_reject_acks_and_marks_rejected(self, db_engine, client):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            events = await _consume_sse(
                client, _url(fix), json={"decision": "reject"}
            )
            completed = events[-1]
            assert isinstance(completed, TurnCompleted)
            assert completed.terminal_state == "rejected"
            assert not _EXECUTOR_CALLS

            async with AsyncSession(bind=db_engine) as q:
                row = (
                    await q.execute(
                        select(PendingAction).where(
                            PendingAction.id == fix.action_id
                        )
                    )
                ).scalar_one()
                assert row.status == PendingActionStatus.REJECTED
        finally:
            await fix.cleanup()
