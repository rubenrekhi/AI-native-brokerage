"""End-to-end smoke test for ``run_agent_turn`` against real Anthropic.

Until the chat-turn endpoint (A1.9) lands, this is the only way to prove
the agent loop works against the real Anthropic API. The integration
tests at ``tests/ai/integration/test_loop_persistence.py`` mock Anthropic
and only verify the persistence flow.

Run:
    uv run python scripts/ai_loop_smoke.py

Prereqs:
    - ``make infra`` running (local Supabase + Redis)
    - ``make migrate`` applied
    - ``ANTHROPIC_API_KEY`` set in ``.env`` (real key)

Behaviour:
    - Inserts a fresh ``auth.users`` + ``user_profiles`` + ``conversations``
      row in a committed setup session.
    - Calls ``run_agent_turn`` with the SMOKE model (Haiku) to keep cost
      under ~1¢ per run.
    - Verifies the persistence shape: ``messages`` (user + assistant),
      ``agent_turns`` (terminal_state='end_turn', cost > 0), and
      ``model_invocations`` (one row, full JSONB payloads).
    - Cleans up every row it created in a ``finally`` block — the DB is
      bit-for-bit identical before and after a successful run.

Exits 0 on PASS, non-zero on FAIL. Output is human-readable so a CI gate
isn't needed; if you want to grep, the last line is always
``RESULT: PASSED`` or ``RESULT: FAILED``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

# Make ``app`` importable when invoked as a script (Python adds the script's
# parent dir to sys.path, not the project root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.ai.anthropic_client import create_anthropic_client  # noqa: E402
from app.ai.models import MODELS  # noqa: E402
from app.ai.prompts import SYSTEM_PROMPT_V1  # noqa: E402
from app.ai.runtime.caps import HardCaps  # noqa: E402
from app.ai.runtime.db import make_session_factory  # noqa: E402
from app.ai.runtime.loop import run_agent_turn  # noqa: E402
from app.ai.runtime.types import EMPTY_REGISTRY, ModelConfig  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.models.agent_turn import AgentTurn  # noqa: E402
from app.models.message import Message as MessageRow  # noqa: E402
from app.models.model_invocation import ModelInvocation  # noqa: E402
from app.repositories.conversation import ConversationRepository  # noqa: E402

USER_MESSAGE = "Reply with exactly the word PONG and nothing else."


async def _seed(user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    """Insert ``auth.users`` + ``user_profiles`` + ``conversations`` rows.

    Both inserts use ``ON CONFLICT DO NOTHING`` because Supabase has a
    trigger on ``auth.users`` that auto-creates a ``user_profiles`` row —
    a second explicit insert would otherwise collide. Idempotent.
    """
    email = f"ai-smoke-{user_id}@test.local"
    async with AsyncSession(bind=engine, expire_on_commit=False) as setup:
        await setup.execute(
            text(
                """
                INSERT INTO auth.users (
                    id, instance_id, email, encrypted_password,
                    aud, role, raw_app_meta_data, raw_user_meta_data,
                    created_at, updated_at, confirmation_token, email_change,
                    email_change_token_new, recovery_token
                ) VALUES (
                    :id, '00000000-0000-0000-0000-000000000000', :email, '',
                    'authenticated', 'authenticated', '{}', '{}',
                    now(), now(), '', '', '', ''
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": user_id, "email": email},
        )
        await setup.execute(
            text(
                """
                INSERT INTO user_profiles (id, email, created_at, updated_at)
                VALUES (:id, :email, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": user_id, "email": email},
        )
        await ConversationRepository.create_conversation(
            setup, conversation_id=conversation_id, user_id=user_id
        )
        await setup.commit()


async def _verify(conversation_id: uuid.UUID) -> list[str]:
    """Return a list of failure messages (empty list = pass)."""
    failures: list[str] = []
    async with AsyncSession(bind=engine, expire_on_commit=False) as v:
        msgs = list(
            (
                await v.execute(
                    select(MessageRow)
                    .where(MessageRow.conversation_id == conversation_id)
                    .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
                )
            )
            .scalars()
            .all()
        )
        if len(msgs) != 2:
            failures.append(
                f"expected 2 messages (user + assistant), got {len(msgs)}"
            )
        else:
            if msgs[0].role != "user":
                failures.append(f"first message role: {msgs[0].role!r}")
            if msgs[1].role != "assistant":
                failures.append(f"second message role: {msgs[1].role!r}")
            if not msgs[1].content_blocks:
                failures.append("assistant message content_blocks is empty")

        turns = list(
            (
                await v.execute(
                    select(AgentTurn).where(
                        AgentTurn.conversation_id == conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(turns) != 1:
            failures.append(f"expected 1 agent_turn, got {len(turns)}")
        else:
            t = turns[0]
            if t.terminal_state != "end_turn":
                failures.append(f"terminal_state: {t.terminal_state!r}")
            if t.error_code is not None:
                failures.append(f"error_code: {t.error_code!r}")
            if t.iterations_count != 1:
                failures.append(f"iterations_count: {t.iterations_count}")
            if t.total_cost_usd_micros <= 0:
                failures.append(
                    f"total_cost_usd_micros: {t.total_cost_usd_micros}"
                )

            invs = list(
                (
                    await v.execute(
                        select(ModelInvocation).where(
                            ModelInvocation.agent_turn_id == t.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(invs) != 1:
                failures.append(
                    f"expected 1 model_invocation, got {len(invs)}"
                )
            else:
                inv = invs[0]
                if not inv.request_system:
                    failures.append("request_system is empty")
                if not inv.request_messages:
                    failures.append("request_messages is empty")
                if not inv.response_content:
                    failures.append("response_content is empty")
                if inv.input_tokens <= 0:
                    failures.append(f"input_tokens: {inv.input_tokens}")
                if inv.output_tokens <= 0:
                    failures.append(f"output_tokens: {inv.output_tokens}")
    return failures


async def _cleanup(user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    """Delete every row this script may have created. Safe to call even if
    the run failed mid-way — uses ``DELETE`` rather than relying on FKs."""
    async with AsyncSession(bind=engine, expire_on_commit=False) as cleanup:
        await cleanup.execute(
            text(
                "DELETE FROM tool_executions WHERE model_invocation_id IN ("
                "SELECT id FROM model_invocations WHERE agent_turn_id IN ("
                "SELECT id FROM agent_turns WHERE conversation_id = :id))"
            ),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text(
                "DELETE FROM model_invocations WHERE agent_turn_id IN ("
                "SELECT id FROM agent_turns WHERE conversation_id = :id)"
            ),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM agent_turns WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM messages WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
        await cleanup.execute(
            text("DELETE FROM user_profiles WHERE id = :id"),
            {"id": user_id},
        )
        await cleanup.execute(
            text("DELETE FROM auth.users WHERE id = :id"),
            {"id": user_id},
        )
        await cleanup.commit()


async def main() -> int:
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith(
        "your-"
    ):
        print(
            "ERROR: ANTHROPIC_API_KEY not set in .env (or still the placeholder)",
            file=sys.stderr,
        )
        return 2

    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    print(f"user_id           = {user_id}")
    print(f"conversation_id   = {conversation_id}")
    print(f"model             = {MODELS.SMOKE}")
    print(f"prompt            = {USER_MESSAGE!r}")
    print()

    client = create_anthropic_client()
    try:
        await _seed(user_id, conversation_id)
        result = await run_agent_turn(
            user_id=user_id,
            conversation_id=conversation_id,
            user_message=USER_MESSAGE,
            anthropic_client=client,
            db_factory=make_session_factory(engine),
            tool_registry=EMPTY_REGISTRY,
            system_prompt=SYSTEM_PROMPT_V1,
            model_config=ModelConfig(model_id=MODELS.SMOKE),
            hard_caps=HardCaps(),
        )
        print(f"terminal_state    = {result.terminal_state}")
        print(f"iterations_count  = {result.iterations_count}")
        print(f"total_cost_µUSD   = {result.total_cost_usd_micros}")
        print("assistant blocks:")
        for block in result.assistant_message_blocks:
            print(f"  {block}")
        print()

        failures = await _verify(conversation_id)
        if failures:
            print("PERSISTENCE CHECKS FAILED:")
            for msg in failures:
                print(f"  - {msg}")
            print("\nRESULT: FAILED")
            return 1

        print("All persistence checks passed.")
        print("\nRESULT: PASSED")
        return 0
    except Exception as exc:
        print(f"\nUNHANDLED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("\nRESULT: FAILED", file=sys.stderr)
        return 1
    finally:
        await client.close()
        try:
            await _cleanup(user_id, conversation_id)
            print("Cleanup: all rows deleted.")
        except Exception as exc:
            print(
                f"WARNING: cleanup failed ({type(exc).__name__}: {exc}). "
                f"Manual delete may be required for user {user_id} / "
                f"conversation {conversation_id}.",
                file=sys.stderr,
            )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
