"""Unit tests for the conversation title / preview derivation helpers
(SEV-564). Pure functions, no DB."""

from app.repositories.conversation import (
    _derive_title_from_blocks,
    extract_text_preview,
)


class TestDeriveTitleFromBlocks:
    def test_returns_first_text_block_text(self):
        blocks = [{"type": "text", "text": "How is AAPL?"}]
        assert _derive_title_from_blocks(blocks) == "How is AAPL?"

    def test_truncates_long_text_with_ellipsis(self):
        long_text = "A" * 100
        title = _derive_title_from_blocks([{"type": "text", "text": long_text}])
        # Default _TITLE_MAX_CHARS is 40 — so the result is ≤ 40 chars and
        # ends with an ellipsis.
        assert title is not None
        assert len(title) <= 40
        assert title.endswith("…")

    def test_collapses_internal_whitespace(self):
        # Multiple spaces / newlines should collapse so the sidebar label
        # doesn't render with awkward indentation.
        blocks = [{"type": "text", "text": "Hello\n\n  world"}]
        assert _derive_title_from_blocks(blocks) == "Hello world"

    def test_returns_none_when_no_text_block(self):
        blocks = [{"type": "status", "label": "Searching", "state": "active"}]
        assert _derive_title_from_blocks(blocks) is None

    def test_returns_none_for_empty_text(self):
        assert _derive_title_from_blocks([{"type": "text", "text": ""}]) is None
        assert (
            _derive_title_from_blocks([{"type": "text", "text": "   "}]) is None
        )

    def test_skips_blocks_without_text_field(self):
        blocks = [
            {"type": "text", "block_id": "1"},  # missing 'text'
            {"type": "text", "text": "real one"},
        ]
        assert _derive_title_from_blocks(blocks) == "real one"

    def test_returns_none_for_empty_block_list(self):
        assert _derive_title_from_blocks([]) is None

    def test_exact_boundary_no_ellipsis(self):
        # Exactly _TITLE_MAX_CHARS (40) chars — no truncation, no ellipsis.
        text = "A" * 40
        assert _derive_title_from_blocks([{"type": "text", "text": text}]) == text


class TestExtractTextPreview:
    def test_returns_first_text_block(self):
        blocks = [{"type": "text", "text": "Sure — based on your portfolio"}]
        assert extract_text_preview(blocks) == "Sure — based on your portfolio"

    def test_truncates_long_text(self):
        long_text = "B" * 200
        preview = extract_text_preview([{"type": "text", "text": long_text}])
        assert preview is not None
        assert len(preview) <= 120
        assert preview.endswith("…")

    def test_returns_none_for_empty_or_missing(self):
        assert extract_text_preview(None) is None
        assert extract_text_preview([]) is None
        assert (
            extract_text_preview(
                [{"type": "status", "label": "x", "state": "active"}]
            )
            is None
        )

    def test_respects_custom_max_chars(self):
        text = "C" * 50
        preview = extract_text_preview(
            [{"type": "text", "text": text}], max_chars=10
        )
        assert preview is not None
        assert len(preview) <= 10
