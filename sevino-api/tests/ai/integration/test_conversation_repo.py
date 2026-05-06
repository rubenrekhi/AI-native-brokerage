"""Integration tests for ConversationRepository against real local Postgres."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_turn import AgentTurn
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.model_invocation import ModelInvocation
from app.models.tool_execution import ToolExecution
from app.exceptions import NotFoundError
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync, insert_auth_user

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


# ---------- helpers ----------


async def _make_conversation(
    db: AsyncSession, user_id: uuid.UUID, **overrides
) -> Conversation:
    defaults: dict = {"conversation_id": uuid.uuid4(), "user_id": user_id}
    defaults.update(overrides)
    return await ConversationRepository.create_conversation(db, **defaults)


async def _make_user_message(
    db: AsyncSession, conversation_id: uuid.UUID, **overrides
) -> Message:
    defaults: dict = {
        "conversation_id": conversation_id,
        "content_blocks": [{"type": "text", "text": "hi"}],
    }
    defaults.update(overrides)
    return await ConversationRepository.append_user_message(db, **defaults)


async def _make_agent_turn(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    **overrides,
) -> AgentTurn:
    defaults: dict = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "prompt_hash": "abc123",
        "model_id": "claude-sonnet-4-6",
    }
    defaults.update(overrides)
    return await ConversationRepository.start_agent_turn(db, **defaults)


# ---------- create_conversation ----------


class TestCreateConversation:
    async def test_persists_with_given_id(
        self, db_session: AsyncSession, test_user
    ):
        conv_id = uuid.uuid4()

        conv = await ConversationRepository.create_conversation(
            db_session, conversation_id=conv_id, user_id=test_user
        )

        assert conv.id == conv_id
        assert conv.user_id == test_user
        assert conv.title is None

        # Round-trip via the same session
        result = await db_session.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        fetched = result.scalar_one()
        assert fetched.id == conv_id
        assert fetched.user_id == test_user

    async def test_persists_with_title(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user, title="My chat")

        assert conv.title == "My chat"


# ---------- load_history ----------


class TestLoadHistory:
    async def test_empty_returns_empty_list(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)

        history = await ConversationRepository.load_history(db_session, conv.id)

        assert history == []

    async def test_returns_messages_in_creation_order(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)

        first = await ConversationRepository.append_user_message(
            db_session,
            conversation_id=conv.id,
            content_blocks=[{"type": "text", "text": "first"}],
        )
        second = await ConversationRepository.append_assistant_message(
            db_session,
            conversation_id=conv.id,
            content_blocks=[{"type": "text", "text": "second"}],
        )
        third = await ConversationRepository.append_user_message(
            db_session,
            conversation_id=conv.id,
            content_blocks=[{"type": "text", "text": "third"}],
        )

        # In production, the agent loop's session-per-write pattern ensures
        # each insert gets a distinct ``now()`` timestamp. In a single test
        # transaction, ``now()`` is fixed at transaction start, so we set
        # ``created_at`` explicitly to validate the ordering contract.
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first.created_at = base
        second.created_at = base + timedelta(seconds=1)
        third.created_at = base + timedelta(seconds=2)
        await db_session.flush()

        history = await ConversationRepository.load_history(db_session, conv.id)

        assert [m.id for m in history] == [first.id, second.id, third.id]
        assert [m.role for m in history] == ["user", "assistant", "user"]

    async def test_only_returns_messages_for_given_conversation(
        self, db_session: AsyncSession, test_user
    ):
        conv_a = await _make_conversation(db_session, test_user)
        conv_b = await _make_conversation(db_session, test_user)

        msg_a = await _make_user_message(db_session, conv_a.id)
        await _make_user_message(db_session, conv_b.id)

        history = await ConversationRepository.load_history(db_session, conv_a.id)

        assert [m.id for m in history] == [msg_a.id]


# ---------- append_user_message / append_assistant_message ----------



class TestAppendMessages:
    async def test_user_message_persists_role_and_blocks(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        blocks = [{"type": "text", "text": "hello world"}]

        msg = await ConversationRepository.append_user_message(
            db_session, conversation_id=conv.id, content_blocks=blocks
        )

        assert msg.role == "user"
        assert msg.content_blocks == blocks
        assert msg.conversation_id == conv.id

    async def test_assistant_message_persists_role_and_blocks(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        blocks = [
            {"type": "text", "text": "AMD is at $100"},
            {
                "type": "stock_card",
                "block_id": "blk_1",
                "symbol": "AMD",
                "price": 100.0,
            },
        ]

        msg = await ConversationRepository.append_assistant_message(
            db_session, conversation_id=conv.id, content_blocks=blocks
        )

        assert msg.role == "assistant"
        assert msg.content_blocks == blocks


# ---------- start_agent_turn / complete_agent_turn ----------


class TestAgentTurnLifecycle:
    async def test_start_agent_turn_persists_with_zero_totals_and_no_terminal_state(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        user_msg = await _make_user_message(db_session, conv.id)

        turn = await ConversationRepository.start_agent_turn(
            db_session,
            conversation_id=conv.id,
            user_id=test_user,
            user_message_id=user_msg.id,
            prompt_hash="hash-abc",
            model_id="claude-sonnet-4-6",
        )

        assert turn.conversation_id == conv.id
        assert turn.user_id == test_user
        assert turn.user_message_id == user_msg.id
        assert turn.prompt_hash == "hash-abc"
        assert turn.model_id == "claude-sonnet-4-6"
        assert turn.terminal_state is None
        assert turn.completed_at is None

        # Server defaults populated after flush
        await db_session.refresh(turn)
        assert turn.iterations_count == 0
        assert turn.total_input_tokens == 0
        assert turn.total_output_tokens == 0
        assert turn.total_cost_usd_micros == 0

    async def test_complete_agent_turn_sets_terminal_state_and_completed_at(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        completed = await ConversationRepository.complete_agent_turn(
            db_session,
            agent_turn_id=turn.id,
            terminal_state="end_turn",
            iterations_count=2,
            total_input_tokens=500,
            total_output_tokens=120,
            total_cost_usd_micros=4_200,
        )

        assert completed.id == turn.id
        assert completed.terminal_state == "end_turn"
        assert completed.completed_at is not None
        assert completed.iterations_count == 2
        assert completed.total_input_tokens == 500
        assert completed.total_output_tokens == 120
        assert completed.total_cost_usd_micros == 4_200

    async def test_complete_agent_turn_can_link_assistant_message(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)
        assistant_msg = (
            await ConversationRepository.append_assistant_message(
                db_session,
                conversation_id=conv.id,
                content_blocks=[{"type": "text", "text": "answer"}],
            )
        )

        completed = await ConversationRepository.complete_agent_turn(
            db_session,
            agent_turn_id=turn.id,
            terminal_state="end_turn",
            assistant_message_id=assistant_msg.id,
        )

        assert completed.assistant_message_id == assistant_msg.id

    async def test_complete_agent_turn_records_cancellation_reason(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        completed = await ConversationRepository.complete_agent_turn(
            db_session,
            agent_turn_id=turn.id,
            terminal_state="cancelled",
            cancellation_reason="client_disconnect",
        )

        assert completed.terminal_state == "cancelled"
        assert completed.cancellation_reason == "client_disconnect"

    async def test_complete_agent_turn_raises_not_found_for_unknown_id(
        self, db_session: AsyncSession
    ):
        with pytest.raises(NotFoundError):
            await ConversationRepository.complete_agent_turn(
                db_session,
                agent_turn_id=uuid.uuid4(),
                terminal_state="end_turn",
            )

    async def test_complete_agent_turn_rejects_unknown_kwargs(
        self, db_session: AsyncSession, test_user
    ):
        # Explicit signature means typos surface as ``TypeError`` instead of
        # being silently dropped (the previous ``**fields`` behaviour).
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        with pytest.raises(TypeError):
            await ConversationRepository.complete_agent_turn(
                db_session,
                agent_turn_id=turn.id,
                terminal_state="end_turn",
                assistant_msg_id=uuid.uuid4(),  # typo
            )


# ---------- record_model_invocation ----------


class TestRecordModelInvocation:
    async def test_persists_request_response_jsonb_payloads(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        request_messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ]
        response_content = [
            {
                "type": "thinking",
                "thinking": "let me think",
                "signature": "sig_abc",
            },
            {"type": "text", "text": "hello"},
        ]

        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[{"type": "text", "text": "you are sevino"}],
            request_messages=request_messages,
            response_content=response_content,
            stop_reason="end_turn",
            input_tokens=42,
            output_tokens=11,
            thinking_tokens=8,
            cost_usd_micros=1_234,
        )

        assert invocation.agent_turn_id == turn.id
        assert invocation.iteration_index == 0
        assert invocation.agent_role == "main"
        assert invocation.request_messages == request_messages
        assert invocation.response_content == response_content
        assert invocation.stop_reason == "end_turn"
        assert invocation.input_tokens == 42
        assert invocation.output_tokens == 11
        assert invocation.thinking_tokens == 8
        assert invocation.cost_usd_micros == 1_234

    async def test_writes_immediately_visible_within_same_session_before_more_writes(
        self, db_session: AsyncSession, test_user
    ):
        """``record_model_invocation`` must flush per-call so partial agent-loop
        progress is durable mid-turn, not batched until ``complete_agent_turn``.
        """
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )

        # Hit the DB via a fresh SELECT (not the in-memory identity map).
        # If the row weren't flushed, this would return zero.
        raw = await db_session.execute(
            text(
                "SELECT iteration_index FROM model_invocations WHERE id = :id"
            ),
            {"id": invocation.id},
        )
        row = raw.fetchone()
        assert row is not None
        assert row[0] == 0

    async def test_omitted_token_fields_default_to_zero(
        self, db_session: AsyncSession, test_user
    ):
        # Repository drops omitted token kwargs from the INSERT so the
        # column-level ``server_default="0"`` populates them. Locks down
        # the contract: omit a token field, get 0 in the DB.
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )

        await db_session.refresh(invocation)
        assert invocation.input_tokens == 0
        assert invocation.output_tokens == 0
        assert invocation.cache_read_input_tokens == 0
        assert invocation.cache_creation_input_tokens == 0
        assert invocation.thinking_tokens == 0
        assert invocation.cost_usd_micros == 0

    async def test_multiple_invocations_persist_with_distinct_iteration_index(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)

        for i in range(3):
            await ConversationRepository.record_model_invocation(
                db_session,
                agent_turn_id=turn.id,
                iteration_index=i,
                model_id="claude-sonnet-4-6",
                request_system=[],
                request_messages=[],
            )

        result = await db_session.execute(
            select(ModelInvocation)
            .where(ModelInvocation.agent_turn_id == turn.id)
            .order_by(ModelInvocation.iteration_index.asc())
        )
        rows = list(result.scalars().all())

        assert [r.iteration_index for r in rows] == [0, 1, 2]


# ---------- record_tool_execution ----------


class TestRecordToolExecution:
    async def test_persists_payloads_and_status(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)
        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )

        tool_exec = await ConversationRepository.record_tool_execution(
            db_session,
            model_invocation_id=invocation.id,
            tool_name="get_stock_info",
            tool_use_id="toolu_abc",
            input_payload={"symbol": "AMD"},
            output_payload={"price": 100.0},
            status="success",
            internal_trace={"raw_quote": {"bid": 99.95, "ask": 100.05}},
            ui_blocks_emitted=[
                {"type": "stock_card", "block_id": "blk_1", "symbol": "AMD"}
            ],
            upstream_api_calls=[
                {"url": "https://data.sandbox.alpaca.markets/...", "status": 200}
            ],
            latency_ms=120,
        )

        assert tool_exec.model_invocation_id == invocation.id
        assert tool_exec.tool_name == "get_stock_info"
        assert tool_exec.tool_use_id == "toolu_abc"
        assert tool_exec.input_payload == {"symbol": "AMD"}
        assert tool_exec.output_payload == {"price": 100.0}
        assert tool_exec.status == "success"
        assert tool_exec.internal_trace == {
            "raw_quote": {"bid": 99.95, "ask": 100.05}
        }
        assert tool_exec.ui_blocks_emitted == [
            {"type": "stock_card", "block_id": "blk_1", "symbol": "AMD"}
        ]
        assert tool_exec.latency_ms == 120

    async def test_terminal_status_auto_stamps_completed_at_when_omitted(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)
        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )

        for status in ("success", "error", "cancelled"):
            tool_exec = await ConversationRepository.record_tool_execution(
                db_session,
                model_invocation_id=invocation.id,
                tool_name="get_stock_info",
                tool_use_id=f"toolu_{status}",
                input_payload={},
                status=status,
            )
            assert tool_exec.completed_at is not None

    async def test_explicit_completed_at_is_preserved(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)
        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )
        explicit = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        tool_exec = await ConversationRepository.record_tool_execution(
            db_session,
            model_invocation_id=invocation.id,
            tool_name="get_stock_info",
            tool_use_id="toolu_explicit",
            input_payload={},
            status="success",
            completed_at=explicit,
        )

        assert tool_exec.completed_at == explicit

    async def test_self_referential_parent_link(
        self, db_session: AsyncSession, test_user
    ):
        conv = await _make_conversation(db_session, test_user)
        turn = await _make_agent_turn(db_session, conv.id, test_user)
        invocation = await ConversationRepository.record_model_invocation(
            db_session,
            agent_turn_id=turn.id,
            iteration_index=0,
            model_id="claude-sonnet-4-6",
            request_system=[],
            request_messages=[],
        )

        parent = await ConversationRepository.record_tool_execution(
            db_session,
            model_invocation_id=invocation.id,
            tool_name="propose_trade",
            tool_use_id="toolu_parent",
            input_payload={},
            status="success",
        )
        child = await ConversationRepository.record_tool_execution(
            db_session,
            model_invocation_id=invocation.id,
            parent_tool_execution_id=parent.id,
            tool_name="get_stock_info",
            tool_use_id="toolu_child",
            input_payload={"symbol": "AMD"},
            status="success",
        )

        result = await db_session.execute(
            select(ToolExecution).where(ToolExecution.id == child.id)
        )
        fetched = result.scalar_one()
        assert fetched.parent_tool_execution_id == parent.id


# ---------- concurrency ----------


class TestConcurrentWrites:
    """The agent loop opens a fresh session per write. Verify that multiple
    concurrent ``record_model_invocation`` calls — each on its own session —
    complete without deadlocking. We commit the parent rows in a setup
    session so other sessions can see them, then explicitly delete at
    teardown (the rolling-back test session can't reach them)."""

    async def test_concurrent_record_model_invocation_does_not_deadlock(
        self, db_engine
    ):
        user_id = uuid.uuid4()
        conv_id = uuid.uuid4()
        email = f"concurrent-{user_id}@test.local"
        turn_id: uuid.UUID | None = None

        try:
            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as setup:
                await insert_auth_user(setup, user_id=user_id, email=email)
                await ConversationRepository.create_conversation(
                    setup, conversation_id=conv_id, user_id=user_id
                )
                turn = await ConversationRepository.start_agent_turn(
                    setup,
                    conversation_id=conv_id,
                    user_id=user_id,
                    prompt_hash="hash",
                    model_id="claude-sonnet-4-6",
                )
                turn_id = turn.id
                await setup.commit()

            async def write_invocation(idx: int) -> uuid.UUID:
                async with AsyncSession(
                    bind=db_engine, expire_on_commit=False
                ) as session:
                    inv = await ConversationRepository.record_model_invocation(
                        session,
                        agent_turn_id=turn_id,
                        iteration_index=idx,
                        model_id="claude-sonnet-4-6",
                        request_system=[],
                        request_messages=[],
                    )
                    await session.commit()
                    return inv.id

            async with asyncio.timeout(10):
                ids = await asyncio.gather(
                    *[write_invocation(i) for i in range(8)]
                )

            assert len(set(ids)) == 8

            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as verify:
                result = await verify.execute(
                    select(ModelInvocation).where(
                        ModelInvocation.agent_turn_id == turn_id
                    )
                )
                assert len(list(result.scalars().all())) == 8
        finally:
            # Delete child-to-parent so the test stays self-cleaning even if
            # a future migration loosens the ON DELETE CASCADE chain.
            async with AsyncSession(
                bind=db_engine, expire_on_commit=False
            ) as cleanup:
                if turn_id is not None:
                    await cleanup.execute(
                        text(
                            "DELETE FROM tool_executions WHERE "
                            "model_invocation_id IN ("
                            "SELECT id FROM model_invocations "
                            "WHERE agent_turn_id = :id)"
                        ),
                        {"id": turn_id},
                    )
                    await cleanup.execute(
                        text(
                            "DELETE FROM model_invocations "
                            "WHERE agent_turn_id = :id"
                        ),
                        {"id": turn_id},
                    )
                await cleanup.execute(
                    text("DELETE FROM agent_turns WHERE user_id = :id"),
                    {"id": user_id},
                )
                await cleanup.execute(
                    text("DELETE FROM conversations WHERE user_id = :id"),
                    {"id": user_id},
                )
                await cleanup.execute(
                    text("DELETE FROM auth.users WHERE id = :id"),
                    {"id": user_id},
                )
                await cleanup.commit()
