"""Integration test: ``messages.content_blocks`` JSONB round-trips a list of
:class:`Block` dicts (SEV-480 / B1.1, SEV-496 / C1.3).

The unit tests in ``tests/ai/unit/test_blocks.py`` cover the discriminator in
isolation; this test closes the loop by writing serialised blocks through the
real JSONB column and re-validating on read.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.blocks import (
    Bar,
    BlockListAdapter,
    StatusBlock,
    StockCardBlock,
    TextBlock,
)
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
        StockCardBlock(
            block_id="blk_card",
            symbol="AMD",
            company_name="Advanced Micro Devices Inc.",
            logo_url="https://example.com/logos/amd.png",
            price=184.92,
            change_abs=2.12,
            change_pct=0.0116,
            color_state="positive",
            bars=[
                Bar(t="2026-04-29T13:30:00Z", c=182.80),
                Bar(t="2026-04-29T13:31:00Z", c=184.92),
            ],
            range="1D",
            range_options=["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"],
        ),
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
