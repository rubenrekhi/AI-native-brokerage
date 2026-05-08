"""Unit tests for ``app.ai.blocks`` (SEV-480 / B1.1, SEV-496 / C1.3).

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
    Bar,
    BlockAdapter,
    BlockListAdapter,
    StatusBlock,
    StockCardBlock,
    TextBlock,
)


def _stock_card_payload() -> dict:
    """Reference StockCardBlock dict — used across discriminator and roundtrip
    tests so changes to the schema only need updating in one place.
    """
    return {
        "type": "stock_card",
        "block_id": "blk_card",
        "symbol": "AMD",
        "company_name": "Advanced Micro Devices Inc.",
        "logo_url": "https://example.com/logos/amd.png",
        "price": 184.92,
        "change_abs": 2.12,
        "change_pct": 0.0116,
        "color_state": "positive",
        "bars": [
            {"t": "2026-04-29T13:30:00Z", "c": 182.80},
            {"t": "2026-04-29T13:31:00Z", "c": 183.50},
            {"t": "2026-04-29T13:32:00Z", "c": 184.92},
        ],
        "range": "1D",
        "range_options": ["1D", "1W", "1M", "3M", "6M", "1Y", "ALL"],
    }


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

    def test_stock_card_payload_validates_to_stock_card_block(self):
        block = BlockAdapter.validate_python(_stock_card_payload())

        assert isinstance(block, StockCardBlock)
        assert block.symbol == "AMD"
        assert block.color_state == "positive"
        assert len(block.bars) == 3
        assert isinstance(block.bars[0], Bar)
        assert block.bars[0].c == pytest.approx(182.80)

    def test_unknown_type_rejected(self):
        # Pydantic checks the discriminator before per-field validation, so an
        # unknown tag fails before any of the variants is even attempted.
        with pytest.raises(ValidationError):
            BlockAdapter.validate_python(
                {"type": "image", "block_id": "x", "url": "https://example.com"}
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

    def test_stock_card_block_json_roundtrip_preserves_variant(self):
        original = StockCardBlock.model_validate(_stock_card_payload())

        as_json = original.model_dump_json()
        restored = BlockAdapter.validate_json(as_json)

        assert isinstance(restored, StockCardBlock)
        assert restored == original

    def test_dump_always_includes_type_discriminator(self):
        # The wire format must always carry ``type`` so the iOS decoder can
        # dispatch — guards against a future Pydantic config that excludes
        # default values from ``model_dump``.
        text_dump = TextBlock(block_id="blk_1", text="hi").model_dump()
        status_dump = StatusBlock(
            block_id="blk_2", label="x", state="active"
        ).model_dump()
        stock_card_dump = StockCardBlock.model_validate(
            _stock_card_payload()
        ).model_dump()

        assert text_dump["type"] == "text"
        assert status_dump["type"] == "status"
        assert stock_card_dump["type"] == "stock_card"

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
            _stock_card_payload(),
        ]

        restored = BlockListAdapter.validate_python(items)

        assert len(restored) == 3
        assert isinstance(restored[0], StatusBlock)
        assert isinstance(restored[1], TextBlock)
        assert isinstance(restored[2], StockCardBlock)

    def test_list_json_roundtrip_preserves_order_and_variants(self):
        original = [
            StatusBlock(block_id="blk_1", label="Loading", state="active"),
            TextBlock(block_id="blk_2", text="hello"),
            StockCardBlock.model_validate(_stock_card_payload()),
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


class TestStockCardBlockShape:
    def test_logo_url_defaults_to_none(self):
        # The tool may not always have a logo for a symbol; ``logo_url`` is
        # the only optional field on the block, so the absence of a logo
        # must validate cleanly.
        payload = _stock_card_payload()
        del payload["logo_url"]

        block = BlockAdapter.validate_python(payload)

        assert isinstance(block, StockCardBlock)
        assert block.logo_url is None

    @pytest.mark.parametrize(
        "color_state", ["positive", "negative", "neutral"]
    )
    def test_valid_color_states_accepted(self, color_state):
        payload = _stock_card_payload()
        payload["color_state"] = color_state

        block = BlockAdapter.validate_python(payload)

        assert isinstance(block, StockCardBlock)
        assert block.color_state == color_state

    def test_invalid_color_state_rejected(self):
        # iOS's ``Codable`` decoder maps this to a tagged enum — anything
        # outside the literal set is a wire-format violation, so it must
        # fail loudly on the backend.
        payload = _stock_card_payload()
        payload["color_state"] = "blue"

        with pytest.raises(ValidationError):
            BlockAdapter.validate_python(payload)

    def test_bars_validate_to_bar_instances(self):
        # Nested ``Bar`` objects must come back typed (not raw dicts) so
        # downstream consumers — e.g. the SSE emitter computing patches —
        # don't have to repeat validation.
        block = StockCardBlock.model_validate(_stock_card_payload())

        assert all(isinstance(bar, Bar) for bar in block.bars)
        assert [bar.c for bar in block.bars] == pytest.approx(
            [182.80, 183.50, 184.92]
        )

    def test_bar_with_non_numeric_close_rejected(self):
        payload = _stock_card_payload()
        payload["bars"] = [{"t": "2026-04-29T13:30:00Z", "c": "not a number"}]

        with pytest.raises(ValidationError):
            BlockAdapter.validate_python(payload)
