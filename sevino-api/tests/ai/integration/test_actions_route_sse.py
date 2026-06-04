"""Integration tests for the HIL confirm endpoint
``POST /v1/conversations/{id}/actions/{action_id}``.

The endpoint claims the pending action, runs the handler's side effect, and
drives a full follow-up agent turn seeded by the handler's per-type prompt.
``run_agent_turn`` is patched (it has its own exhaustive coverage in
test_loop / test_chat_endpoint_sse) so these tests focus on the route's logic:
CAS, handler dispatch, marking, and that the turn is driven with the right
seed + ``persist_user_message=False``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.actions import ACTION_HANDLERS, register_action_handler
from app.ai.actions.base import ActionResult
from app.ai.anthropic_client import get_anthropic
from app.ai.observability.langfuse import _NoopLangfuse, get_langfuse
from app.ai.runtime.db import get_db_factory, make_session_factory
from app.ai.transport.events import (
    BlockData,
    BlockEnd,
    BlockStart,
    Event,
    TurnCompleted,
    TurnStarted,
    parse_wire_frame,
)
from app.auth import get_current_user
from app.main import app
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

_TEST_ACTION_TYPE = "test_action"
_HANDLER_CALLS: list[tuple[str, dict[str, Any]]] = []
_RUN_CALLS: list[dict[str, Any]] = []


class _StubHandler:
    async def execute(self, payload, ctx) -> ActionResult:
        _HANDLER_CALLS.append(("execute", payload))
        return ActionResult(
            status="executed",
            resume_prompt="RESUME_SEED",
            summary={"transfer_id": "xfer_1"},
        )

    def reject_prompt(self, payload) -> str:
        _HANDLER_CALLS.append(("reject", payload))
        return "REJECT_SEED"


async def _fake_run_agent_turn(**kwargs):
    _RUN_CALLS.append(kwargs)
    emitter = kwargs["sse_emitter"]
    tid = uuid.uuid4()
    await emitter.emit(
        TurnStarted(
            turn_id=tid,
            conversation_id=kwargs["conversation_id"],
            card_context_source=None,
        )
    )
    await emitter.emit(
        BlockStart(
            block={"type": "text", "block_id": "b1", "text": "Done."}
        )
    )
    await emitter.emit(BlockEnd(block_id="b1"))
    await emitter.emit(
        TurnCompleted(
            turn_id=tid,
            terminal_state="end_turn",
            total_cost_usd_micros=0,
            iterations_count=1,
        )
    )
    return SimpleNamespace(
        turn_id=tid,
        terminal_state="end_turn",
        assistant_message_blocks=[
            {"type": "text", "block_id": "b1", "text": "Done."}
        ],
        total_cost_usd_micros=0,
        iterations_count=1,
    )


async def _consume_sse(
    client: AsyncClient, url: str, *, json: dict[str, Any]
) -> list[Event]:
    async with client.stream("POST", url, json=json) as response:
        assert response.status_code == 200, await response.aread()
        body = (await response.aread()).decode("utf-8")
    return [
        parse_wire_frame(frame)
        for frame in body.replace("\r\n", "\n").split("\n\n")
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
            for table, col, val in (
                ("pending_actions", "conversation_id", self.conversation_id),
                ("messages", "conversation_id", self.conversation_id),
                ("agent_turns", "conversation_id", self.conversation_id),
                ("conversations", "id", self.conversation_id),
                ("user_profiles", "id", self.user_id),
                ("auth.users", "id", self.user_id),
            ):
                await c.execute(
                    text(f"DELETE FROM {table} WHERE {col} = :v"), {"v": val}
                )
            await c.commit()


async def _seed(
    engine,
    *,
    expires_in_s: int = 300,
    status: str | None = None,
    action_type: str = _TEST_ACTION_TYPE,
) -> _Fixture:
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    action_id = uuid.uuid4()
    async with AsyncSession(bind=engine, expire_on_commit=False) as setup:
        await insert_auth_user(
            setup, user_id=user_id, email=f"actions-{user_id}@test.local"
        )
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
            action_type=action_type,
            payload={"amount": "10.00", "direction": "INCOMING"},
            preview={"action_id": str(action_id), "block_id": "card-1"},
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=expires_in_s),
        )
        if status is not None:
            await setup.execute(
                text("UPDATE pending_actions SET status=:s WHERE id=:id"),
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
def _wire(monkeypatch):
    _HANDLER_CALLS.clear()
    _RUN_CALLS.clear()
    if _TEST_ACTION_TYPE not in ACTION_HANDLERS:
        register_action_handler(_TEST_ACTION_TYPE, _StubHandler())
    monkeypatch.setattr(
        "app.routes.actions.run_agent_turn", _fake_run_agent_turn
    )
    yield
    ACTION_HANDLERS.pop(_TEST_ACTION_TYPE, None)
    _HANDLER_CALLS.clear()
    _RUN_CALLS.clear()


@pytest.fixture
async def client(db_engine):
    db_factory = make_session_factory(db_engine)
    app.dependency_overrides[get_db_factory] = lambda: db_factory
    app.dependency_overrides[get_anthropic] = lambda: object()
    app.dependency_overrides[get_langfuse] = lambda: _NoopLangfuse()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": TEST_API_KEY},
    ) as ac:
        yield ac
    for dep in (get_db_factory, get_anthropic, get_langfuse, get_current_user):
        app.dependency_overrides.pop(dep, None)


def _auth_as(user_id: uuid.UUID) -> None:
    app.dependency_overrides[get_current_user] = lambda: str(user_id)


def _url(fix: _Fixture) -> str:
    return (
        f"/v1/conversations/{fix.conversation_id}/actions/{fix.action_id}"
    )


class TestConfirm:
    async def test_confirm_executes_then_drives_seeded_turn(
        self, db_engine, client
    ):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            events = await _consume_sse(
                client, _url(fix), json={"decision": "confirm"}
            )
            # The card resolves first: a block_data patch flips the originating
            # card to its terminal status before the resumed turn streams.
            assert type(events[0]) is BlockData
            assert events[0].block_id == "card-1"
            assert events[0].data == {"status": "executed"}
            assert type(events[1]) is TurnStarted
            assert type(events[-1]) is TurnCompleted

            # Handler side effect ran with the persisted payload.
            assert ("execute", {"amount": "10.00", "direction": "INCOMING"}) in _HANDLER_CALLS
            # A full follow-up turn was driven, seeded + system-initiated.
            assert len(_RUN_CALLS) == 1
            assert _RUN_CALLS[0]["user_message"] == "RESUME_SEED"
            assert _RUN_CALLS[0]["persist_user_message"] is False

            async with AsyncSession(bind=db_engine) as q:
                row = (
                    await q.execute(
                        select(PendingAction).where(
                            PendingAction.id == fix.action_id
                        )
                    )
                ).scalar_one()
                assert row.status == PendingActionStatus.EXECUTED
                assert row.result == {"transfer_id": "xfer_1"}
        finally:
            await fix.cleanup()

    async def test_double_confirm_is_refused(self, db_engine, client):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            await _consume_sse(client, _url(fix), json={"decision": "confirm"})
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
            assert not _HANDLER_CALLS
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

    async def test_unsupported_action_type_is_refused(self, db_engine, client):
        fix = await _seed(db_engine, action_type="no_such_handler")
        _auth_as(fix.user_id)
        try:
            resp = await client.post(_url(fix), json={"decision": "confirm"})
            assert resp.status_code == 409
            assert resp.json()["code"] == "ACTION_UNSUPPORTED"
            assert not _RUN_CALLS
        finally:
            await fix.cleanup()


class TestReject:
    async def test_reject_drives_turn_with_reject_seed(
        self, db_engine, client
    ):
        fix = await _seed(db_engine)
        _auth_as(fix.user_id)
        try:
            events = await _consume_sse(
                client, _url(fix), json={"decision": "reject"}
            )
            assert type(events[0]) is BlockData
            assert events[0].block_id == "card-1"
            assert events[0].data == {"status": "rejected"}
            assert type(events[-1]) is TurnCompleted
            assert ("reject", {"amount": "10.00", "direction": "INCOMING"}) in _HANDLER_CALLS
            assert _RUN_CALLS[0]["user_message"] == "REJECT_SEED"
            assert _RUN_CALLS[0]["persist_user_message"] is False

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
