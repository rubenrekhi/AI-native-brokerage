import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.agent_turn import AgentTurn
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.model_invocation import ModelInvocation
from app.models.tool_execution import ToolExecution

# Tool execution statuses that imply the call has finished and
# ``completed_at`` should be stamped if the caller didn't pass it.
_TERMINAL_TOOL_STATUSES = frozenset({"success", "error", "cancelled"})

# Max characters for an auto-derived conversation title (first user message).
_TITLE_MAX_CHARS = 40


def _derive_title_from_blocks(content_blocks: list[dict[str, Any]]) -> str | None:
    """Pull a stable title out of the first user message.

    Looks for the first ``{"type": "text", ...}`` block, collapses internal
    whitespace, and truncates to roughly :data:`_TITLE_MAX_CHARS`. Returns
    ``None`` if no text block is present so the column stays NULL — list
    callers fall back to a client-side placeholder rather than rendering an
    empty string.
    """
    for block in content_blocks:
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        cleaned = " ".join(text.split())
        if not cleaned:
            continue
        if len(cleaned) <= _TITLE_MAX_CHARS:
            return cleaned
        return cleaned[: _TITLE_MAX_CHARS - 1].rstrip() + "…"
    return None


def extract_text_preview(
    content_blocks: list[dict[str, Any]] | None, max_chars: int = 120
) -> str | None:
    """First-text-block preview, used by the list endpoint.

    Mirrors :func:`_derive_title_from_blocks` but allows a longer truncation
    so the sidebar shows enough of the assistant's reply (or user prompt) to
    be useful at a glance.
    """
    if not content_blocks:
        return None
    for block in content_blocks:
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        cleaned = " ".join(text.split())
        if not cleaned:
            continue
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max_chars - 1].rstrip() + "…"
    return None


class ConversationRepository:
    """Data access for conversations, messages, and the agent runtime audit
    trail (agent_turns, model_invocations, tool_executions).

    Each method flushes its own write but does not commit. Transaction
    boundaries are owned by the caller — typically a session factory that
    opens a fresh session per write so that mid-turn audit rows are durable
    even if a later step fails.
    """

    @staticmethod
    async def create_conversation(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            id=conversation_id, user_id=user_id, title=title
        )
        db.add(conversation)
        await db.flush()
        return conversation

    @staticmethod
    async def ensure_owned_conversation(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Conversation:
        """Idempotent insert (decision D6): create the conversation row if
        it doesn't exist, otherwise verify ``user_id`` owns the existing
        row. Raises :class:`NotFoundError` on ownership mismatch — the
        same response shape as a missing row, so the endpoint never leaks
        the existence of another user's conversation under that UUID."""
        stmt = (
            pg_insert(Conversation)
            .values(id=conversation_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        await db.execute(stmt)
        await db.flush()
        conversation = await db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.user_id != user_id
            or conversation.is_deleted
        ):
            raise NotFoundError(
                "Conversation not found", resource="conversation"
            )
        return conversation

    @staticmethod
    async def load_history(
        db: AsyncSession, conversation_id: uuid.UUID
    ) -> list[Message]:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_conversations_for_user(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        limit: int,
        cursor_last_message_at: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
    ) -> list[tuple[Conversation, list[dict[str, Any]] | None]]:
        """List a user's conversations ordered by recency.

        Skips rows with NULL ``last_message_at`` (i.e. conversations whose
        first turn hasn't landed yet) so the sidebar only surfaces
        conversations the user has actually engaged with. The
        ``(last_message_at, id)`` tuple is a stable sort key — ``id`` breaks
        ties when two conversations share a timestamp.

        Each row carries the ``content_blocks`` of its most recent message so
        the endpoint can derive a one-line preview without a follow-up
        query. The correlated subquery runs once per row in the result page
        (≤ ``limit`` rows) so the cost is bounded.
        """
        last_blocks_subq = (
            select(Message.content_blocks)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )

        stmt = (
            select(Conversation, last_blocks_subq.label("last_content_blocks"))
            .where(Conversation.user_id == user_id)
            .where(Conversation.last_message_at.is_not(None))
            .where(Conversation.is_deleted == False)  # noqa: E712
        )
        if cursor_last_message_at is not None and cursor_id is not None:
            # Compound row comparison: keep walking down the (timestamp, id)
            # sort key past the cursor's position. NULLs are already excluded
            # by the predicate above, so the tuple ordering is total.
            stmt = stmt.where(
                or_(
                    Conversation.last_message_at < cursor_last_message_at,
                    and_(
                        Conversation.last_message_at == cursor_last_message_at,
                        Conversation.id < cursor_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            Conversation.last_message_at.desc(), Conversation.id.desc()
        ).limit(limit)

        result = await db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    @staticmethod
    async def list_messages_for_conversation(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
    ) -> list[Message]:
        """List a conversation's messages in arrival order, owner-scoped.

        Raises :class:`NotFoundError` when the conversation doesn't exist or
        belongs to another user — same response shape either way so the
        endpoint can't be used to probe for the existence of foreign
        conversation ids.
        """
        conversation = await db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.user_id != user_id
            or conversation.is_deleted
        ):
            raise NotFoundError(
                "Conversation not found", resource="conversation"
            )

        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Message.created_at > cursor_created_at,
                    and_(
                        Message.created_at == cursor_created_at,
                        Message.id > cursor_id,
                    ),
                )
            )
        stmt = stmt.order_by(
            Message.created_at.asc(), Message.id.asc()
        ).limit(limit)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def _append_message(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content_blocks: list[dict[str, Any]],
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content_blocks=content_blocks,
        )
        db.add(message)
        await db.flush()

        # Maintain the denormalised list-view fields on the conversation:
        # * ``last_message_at`` tracks the most recent message for sidebar
        #   sorting. ``GREATEST`` guards against concurrent appends landing
        #   out-of-order — a stale timestamp would push the conversation
        #   down the sidebar by a few seconds until the next turn.
        # * ``title`` is set from the first user message and frozen
        #   afterwards (``CASE WHEN title IS NULL THEN :t ELSE title END``)
        #   so follow-up turns don't rewrite the sidebar label.
        # Single UPDATE keeps the per-message write to one round-trip.
        values: dict[str, Any] = {
            "last_message_at": func.greatest(
                func.coalesce(Conversation.last_message_at, message.created_at),
                message.created_at,
            ),
        }
        if role == "user":
            derived_title = _derive_title_from_blocks(content_blocks)
            if derived_title is not None:
                values["title"] = case(
                    (Conversation.title.is_(None), derived_title),
                    else_=Conversation.title,
                )
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )
        await db.flush()
        return message

    @staticmethod
    async def append_user_message(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content_blocks: list[dict[str, Any]],
    ) -> Message:
        return await ConversationRepository._append_message(
            db,
            conversation_id=conversation_id,
            role="user",
            content_blocks=content_blocks,
        )

    @staticmethod
    async def append_assistant_message(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        content_blocks: list[dict[str, Any]],
    ) -> Message:
        return await ConversationRepository._append_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content_blocks=content_blocks,
        )

    @staticmethod
    async def load_assistant_message_for_turn(
        db: AsyncSession,
        *,
        agent_turn_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> tuple[AgentTurn, Message] | None:
        """Load the ``(turn, assistant_message)`` pair for an idempotent
        replay (B3.2), scoped to ``conversation_id``.

        Returns ``None`` if the turn doesn't exist, has no assistant
        message, or belongs to a different conversation. The
        ``conversation_id`` filter matters because idempotency slots are
        keyed on ``(user_id, idempotency_key)`` only — without this check,
        a user reusing the same key against conversation B would replay
        conversation A's assistant message under B's URL, and the wire
        envelope's ``TurnStarted`` would carry a mismatched
        ``conversation_id``.
        """
        turn = await db.get(AgentTurn, agent_turn_id)
        if turn is None or turn.assistant_message_id is None:
            return None
        if turn.conversation_id != conversation_id:
            return None
        message = await db.get(Message, turn.assistant_message_id)
        if message is None:
            return None
        return turn, message

    @staticmethod
    async def start_agent_turn(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        prompt_hash: str,
        model_id: str,
        user_message_id: uuid.UUID | None = None,
    ) -> AgentTurn:
        turn = AgentTurn(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message_id=user_message_id,
            prompt_hash=prompt_hash,
            model_id=model_id,
        )
        db.add(turn)
        await db.flush()
        return turn

    @staticmethod
    async def complete_agent_turn(
        db: AsyncSession,
        *,
        agent_turn_id: uuid.UUID,
        terminal_state: str,
        assistant_message_id: uuid.UUID | None = None,
        cancellation_reason: str | None = None,
        error_code: str | None = None,
        iterations_count: int | None = None,
        total_input_tokens: int | None = None,
        total_output_tokens: int | None = None,
        total_cache_read_tokens: int | None = None,
        total_cache_creation_tokens: int | None = None,
        total_thinking_tokens: int | None = None,
        total_cost_usd_micros: int | None = None,
    ) -> AgentTurn:
        """Partial update — only fields whose kwargs are non-None are written,
        so callers can target specific terminal-state shapes (cancellation,
        error, success) without clobbering unrelated columns. Raises
        ``NotFoundError`` if the turn does not exist."""
        turn = await db.get(AgentTurn, agent_turn_id)
        if turn is None:
            raise NotFoundError(
                "Agent turn not found", resource="agent_turn"
            )
        turn.terminal_state = terminal_state
        turn.completed_at = datetime.now(timezone.utc)
        if assistant_message_id is not None:
            turn.assistant_message_id = assistant_message_id
        if cancellation_reason is not None:
            turn.cancellation_reason = cancellation_reason
        if error_code is not None:
            turn.error_code = error_code
        if iterations_count is not None:
            turn.iterations_count = iterations_count
        if total_input_tokens is not None:
            turn.total_input_tokens = total_input_tokens
        if total_output_tokens is not None:
            turn.total_output_tokens = total_output_tokens
        if total_cache_read_tokens is not None:
            turn.total_cache_read_tokens = total_cache_read_tokens
        if total_cache_creation_tokens is not None:
            turn.total_cache_creation_tokens = total_cache_creation_tokens
        if total_thinking_tokens is not None:
            turn.total_thinking_tokens = total_thinking_tokens
        if total_cost_usd_micros is not None:
            turn.total_cost_usd_micros = total_cost_usd_micros
        await db.flush()
        return turn

    @staticmethod
    async def record_model_invocation(
        db: AsyncSession,
        *,
        agent_turn_id: uuid.UUID,
        iteration_index: int,
        model_id: str,
        request_system: list[dict[str, Any]],
        request_messages: list[dict[str, Any]],
        agent_role: str = "main",
        request_tools: list[dict[str, Any]] | None = None,
        response_content: list[dict[str, Any]] | None = None,
        stop_reason: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        cache_creation_input_tokens: int | None = None,
        thinking_tokens: int | None = None,
        cost_usd_micros: int | None = None,
        latency_ms: int | None = None,
    ) -> ModelInvocation:
        """Token/cost columns have ``server_default="0"`` — omitted kwargs
        are dropped from the INSERT so the DB default is the single source
        of truth for the zero case."""
        optional: dict[str, Any] = {}
        if input_tokens is not None:
            optional["input_tokens"] = input_tokens
        if output_tokens is not None:
            optional["output_tokens"] = output_tokens
        if cache_read_input_tokens is not None:
            optional["cache_read_input_tokens"] = cache_read_input_tokens
        if cache_creation_input_tokens is not None:
            optional["cache_creation_input_tokens"] = cache_creation_input_tokens
        if thinking_tokens is not None:
            optional["thinking_tokens"] = thinking_tokens
        if cost_usd_micros is not None:
            optional["cost_usd_micros"] = cost_usd_micros

        invocation = ModelInvocation(
            agent_turn_id=agent_turn_id,
            iteration_index=iteration_index,
            model_id=model_id,
            agent_role=agent_role,
            request_system=request_system,
            request_messages=request_messages,
            request_tools=request_tools,
            response_content=response_content,
            stop_reason=stop_reason,
            latency_ms=latency_ms,
            **optional,
        )
        db.add(invocation)
        await db.flush()
        return invocation

    @staticmethod
    async def record_tool_execution(
        db: AsyncSession,
        *,
        model_invocation_id: uuid.UUID,
        tool_name: str,
        tool_use_id: str,
        input_payload: dict[str, Any],
        status: str,
        parent_tool_execution_id: uuid.UUID | None = None,
        output_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
        internal_trace: dict[str, Any] | None = None,
        ui_blocks_emitted: list[dict[str, Any]] | None = None,
        upstream_api_calls: list[dict[str, Any]] | None = None,
        latency_ms: int | None = None,
        completed_at: datetime | None = None,
    ) -> ToolExecution:
        """Auto-stamps ``completed_at`` when ``status`` is terminal and the
        caller did not supply one, so the audit trail can't be left in a
        contradictory state (e.g. ``status='success'`` with ``completed_at``
        NULL)."""
        if completed_at is None and status in _TERMINAL_TOOL_STATUSES:
            completed_at = datetime.now(timezone.utc)
        tool_execution = ToolExecution(
            model_invocation_id=model_invocation_id,
            parent_tool_execution_id=parent_tool_execution_id,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            input_payload=input_payload,
            output_payload=output_payload,
            status=status,
            error_message=error_message,
            internal_trace=internal_trace,
            ui_blocks_emitted=ui_blocks_emitted,
            upstream_api_calls=upstream_api_calls,
            latency_ms=latency_ms,
            completed_at=completed_at,
        )
        db.add(tool_execution)
        await db.flush()
        return tool_execution

    @staticmethod
    async def delete_conversation(
        db: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Soft-delete a conversation owned by *user_id*.

        Sets ``is_deleted = True`` rather than removing the row so
        conversation data is retained for audit / analytics. The list
        endpoint filters out soft-deleted rows. Raises
        :class:`NotFoundError` if the conversation doesn't exist or
        belongs to another user.
        """
        result = await db.execute(
            update(Conversation)
            .where(
                and_(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,  # noqa: E712
                )
            )
            .values(is_deleted=True)
        )
        if result.rowcount == 0:
            raise NotFoundError("Conversation not found")
        await db.flush()
