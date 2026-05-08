"""Unit tests for ``app.ai.blocks`` (SEV-480 / B1.1).

Acceptance criteria from the AI v0 plan:
- Validation of a dict payload dispatches to the correct subclass via the
  ``type`` discriminator.
- Round-trip JSON serialisation preserves the variant.
- (See ``tests/ai/integration/test_blocks_persistence.py`` for the JSONB
  round-trip through ``messages.content_blocks``.)
"""

import pytest
from pydantic import ValidationError

from app.ai.blocks import (
    BlockAdapter,
    BlockListAdapter,
    StatusBlock,
    TextBlock,
)


class TestDiscriminatorDispatch:
    def test_text_payload_validates_to_text_block(self):
        block = BlockAdapter.validate_python(
            {"type": "text", "block_id": "blk_1", "text": "hello"}
        )

        assert isinstance(block, TextBlock)
        assert block.block_id == "blk_1"
        assert block.text == "hello"

    def test_status_payload_validates_to_status_block(self):
        block = BlockAdapter.validate_python(
            {
                "type": "status",
                "block_id": "blk_2",
                "label": "Searching the web",
                "state": "active",
            }
        )

        assert isinstance(block, StatusBlock)
        assert block.block_id == "blk_2"
        assert block.label == "Searching the web"
        assert block.state == "active"

    def test_unknown_type_rejected(self):
        # Pydantic checks the discriminator before per-field validation, so an
        # unknown tag fails before any of the variants is even attempted.
        with pytest.raises(ValidationError):
            BlockAdapter.validate_python(
                {"type": "stock_card", "block_id": "x", "symbol": "AMD"}
            )

    def test_missing_discriminator_rejected(self):
        with pytest.raises(ValidationError):
            BlockAdapter.validate_python({"block_id": "x", "text": "hi"})


class TestRoundTripSerialisation:
    def test_text_block_json_roundtrip_preserves_variant(self):
        original = TextBlock(block_id="blk_1", text="hello world")

        as_json = original.model_dump_json()
        restored = BlockAdapter.validate_json(as_json)

        assert isinstance(restored, TextBlock)
        assert restored == original

    def test_status_block_json_roundtrip_preserves_variant(self):
        original = StatusBlock(
            block_id="blk_2",
            label="Searching",
            state="complete",
        )

        as_json = original.model_dump_json()
        restored = BlockAdapter.validate_json(as_json)

        assert isinstance(restored, StatusBlock)
        assert restored == original

    def test_dump_always_includes_type_discriminator(self):
        # The wire format must always carry ``type`` so the iOS decoder can
        # dispatch — guards against a future Pydantic config that excludes
        # default values from ``model_dump``.
        text_dump = TextBlock(block_id="blk_1", text="hi").model_dump()
        status_dump = StatusBlock(
            block_id="blk_2", label="x", state="active"
        ).model_dump()

        assert text_dump["type"] == "text"
        assert status_dump["type"] == "status"

    def test_list_adapter_dispatches_each_item_independently(self):
        # ``messages.content_blocks`` is ``list[Block]`` — the list-level
        # adapter must dispatch each item through the discriminator.
        items = [
            {
                "type": "status",
                "block_id": "blk_1",
                "label": "Loading",
                "state": "active",
            },
            {"type": "text", "block_id": "blk_2", "text": "Hello, AMD"},
        ]

        restored = BlockListAdapter.validate_python(items)

        assert len(restored) == 2
        assert isinstance(restored[0], StatusBlock)
        assert isinstance(restored[1], TextBlock)

    def test_list_json_roundtrip_preserves_order_and_variants(self):
        original = [
            StatusBlock(block_id="blk_1", label="Loading", state="active"),
            TextBlock(block_id="blk_2", text="hello"),
            StatusBlock(block_id="blk_3", label="Loading", state="complete"),
        ]

        as_json = BlockListAdapter.dump_json(original)
        restored = BlockListAdapter.validate_json(as_json)

        assert restored == original


class TestStatusStateLiteral:
    @pytest.mark.parametrize("state", ["active", "complete", "failed"])
    def test_valid_states_accepted(self, state):
        block = StatusBlock(block_id="blk_1", label="x", state=state)  # type: ignore[arg-type]
        assert block.state == state

    def test_invalid_state_rejected(self):
        # The state literal is a wire-format invariant: any other tag is a
        # contract violation iOS won't decode, so we want it to fail loudly.
        with pytest.raises(ValidationError):
            StatusBlock(block_id="blk_1", label="x", state="pending")  # type: ignore[arg-type]
