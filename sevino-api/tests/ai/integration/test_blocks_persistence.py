"""Integration test: ``messages.content_blocks`` JSONB round-trips a list of
:class:`Block` dicts (SEV-480 / B1.1).

The unit tests in ``tests/ai/unit/test_blocks.py`` cover the discriminator in
isolation; this test closes the loop by writing serialised blocks through the
real JSONB column and re-validating on read.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.blocks import BlockListAdapter, StatusBlock, TextBlock
from app.repositories.conversation import ConversationRepository
from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)


async def test_jsonb_roundtrip_preserves_block_variants(
    db_session: AsyncSession, test_user
):
    conv = await ConversationRepository.create_conversation(
        db_session, conversation_id=uuid.uuid4(), user_id=test_user
    )

    blocks = [
        StatusBlock(block_id="blk_status", label="Searching", state="active"),
        TextBlock(block_id="blk_text", text="AMD is at $100"),
    ]
    serialised = [b.model_dump() for b in blocks]

    msg = await ConversationRepository.append_assistant_message(
        db_session,
        conversation_id=conv.id,
        content_blocks=serialised,
    )

    # The dicts pulled from JSONB must validate back to the same subclasses
    # (and equal values) they came from.
    restored = BlockListAdapter.validate_python(msg.content_blocks)

    assert restored == blocks
