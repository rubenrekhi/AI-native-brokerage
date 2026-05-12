"""Unit tests for ``app.ai.runtime.anthropic_io.scrub_block`` / ``scrub_blocks``.

The scrubber exists because the Anthropic Python SDK's ``ParsedTextBlock``
carries a ``parsed_output`` field for client-side structured-output
convenience. The SDK marks it with ``__api_exclude__ = {"parsed_output"}``
but ``model_dump(mode="json")`` does not honor that marker, so the field
leaks into the dict the loop echoes back to Anthropic on the next
iteration. The API rejects it:

    messages.N.content.M.text.parsed_output: Extra inputs are not permitted

This regression target was captured against the live Anthropic API on PR
#752's first end-to-end test (the first tool to ship in production).

Allowlist coverage is validated against the public Messages API spec at
docs.claude.com/en/api/messages — these tests assert that *every*
documented optional field (``cache_control``, ``citations``, ``caller``)
is preserved through scrubbing, while undocumented SDK-only fields are
dropped.
"""

from __future__ import annotations

from app.ai.runtime.anthropic_io import (
    INPUT_FIELDS_BY_BLOCK_TYPE,
    scrub_block,
    scrub_blocks,
)


class TestScrubText:
    def test_strips_parsed_output(self):
        # ``parsed_output`` is the SDK's ParsedTextBlock convenience field
        # — explicitly marked __api_exclude__ in the SDK and rejected by
        # the API on input.
        block = {
            "type": "text",
            "text": "Sure, let me look that up.",
            "parsed_output": None,
        }
        assert scrub_block(block) == {
            "type": "text",
            "text": "Sure, let me look that up.",
        }

    def test_preserves_citations_null(self):
        # ``citations`` is a documented optional input field. The SDK
        # serialises it as null when there are no citations; null is a
        # valid value and round-trips harmlessly.
        block = {"type": "text", "text": "x", "citations": None}
        assert scrub_block(block) == block

    def test_preserves_citations_with_values(self):
        block = {
            "type": "text",
            "text": "x",
            "citations": [
                {"type": "char_location", "cited_text": "y", "document_index": 0,
                 "document_title": "doc", "start_char_index": 0, "end_char_index": 1},
            ],
        }
        assert scrub_block(block) == block

    def test_preserves_cache_control(self):
        block = {
            "type": "text",
            "text": "x",
            "cache_control": {"type": "ephemeral"},
        }
        assert scrub_block(block) == block

    def test_returns_a_fresh_dict_when_filtering(self):
        # Don't mutate the caller's object — the unscrubbed copy may still
        # be referenced upstream.
        original = {"type": "text", "text": "x", "parsed_output": None}
        scrubbed = scrub_block(original)
        assert scrubbed is not original
        assert "parsed_output" in original


class TestScrubThinking:
    def test_preserves_signature(self):
        # ``signature`` is REQUIRED on the input side when echoing a
        # thinking block back — A1.7 thinking-roundtripping relies on it.
        block = {
            "type": "thinking",
            "thinking": "The user wants AAPL price.",
            "signature": "ABC123==",
        }
        assert scrub_block(block) == block

    def test_strips_unknown_extras(self):
        # Per spec, thinking blocks accept only {type, thinking, signature}.
        # A hypothetical future SDK-only field is dropped.
        block = {
            "type": "thinking",
            "thinking": "x",
            "signature": "S",
            "_internal_marker": "drop me",
        }
        assert scrub_block(block) == {
            "type": "thinking",
            "thinking": "x",
            "signature": "S",
        }


class TestScrubToolUse:
    def test_preserves_caller(self):
        # ``caller`` is a documented optional input field, not an SDK
        # extra. The SDK populates it as ``{"type": "direct"}`` for
        # client-initiated tool calls; the API tolerates and round-trips
        # it cleanly.
        block = {
            "id": "toolu_xyz",
            "name": "get_stock_info",
            "type": "tool_use",
            "input": {"ticker": "AAPL"},
            "caller": {"type": "direct"},
        }
        assert scrub_block(block) == block

    def test_preserves_cache_control(self):
        block = {
            "id": "toolu_xyz",
            "name": "foo",
            "type": "tool_use",
            "input": {},
            "cache_control": {"type": "ephemeral"},
        }
        assert scrub_block(block) == block


class TestScrubRedactedThinking:
    def test_preserves_data_field(self):
        block = {
            "type": "redacted_thinking",
            "data": "<encrypted-blob>",
        }
        assert scrub_block(block) == block


class TestScrubUnknownType:
    def test_pass_through_for_unknown_type(self):
        # New block types added by future SDK versions should round-trip
        # unchanged — better an Anthropic 400 caught in smoke than a
        # silent drop that loses content.
        block = {"type": "future_block_v2", "payload": {"x": 1}}
        assert scrub_block(block) == block

    def test_pass_through_when_type_missing(self):
        block = {"weird": "shape"}
        assert scrub_block(block) == block


class TestScrubBlocks:
    def test_applies_to_every_block(self):
        blocks = [
            {"type": "thinking", "thinking": "...", "signature": "S"},
            {"type": "text", "text": "x", "parsed_output": None, "citations": None},
            {
                "type": "tool_use",
                "id": "t1",
                "name": "foo",
                "input": {},
                "caller": {"type": "direct"},
            },
        ]
        assert scrub_blocks(blocks) == [
            {"type": "thinking", "thinking": "...", "signature": "S"},
            # parsed_output dropped, citations preserved
            {"type": "text", "text": "x", "citations": None},
            # caller preserved (valid input field)
            {
                "type": "tool_use",
                "id": "t1",
                "name": "foo",
                "input": {},
                "caller": {"type": "direct"},
            },
        ]

    def test_empty_list(self):
        assert scrub_blocks([]) == []


class TestRealCapturedPayloadRegression:
    def test_captured_failing_assistant_content_is_scrubbed_clean(self):
        # Verbatim assistant content recorded against the live Anthropic
        # API during PR #752's first end-to-end test. Anthropic 400'd on
        # iteration N+1 with this exact shape; the scrubbed version is
        # what should have been echoed back.
        captured = [
            {
                "type": "thinking",
                "thinking": "The user wants to look up BADTKR123.",
                "signature": "Ep4CClsIDRgC...",
            },
            {
                "text": "Sure, let me look that up for you right now!",
                "type": "text",
                "citations": None,
                "parsed_output": None,
            },
            {
                "id": "toolu_0143Sim15K4D4v3461QZKTaR",
                "name": "get_stock_info",
                "type": "tool_use",
                "input": {"ticker": "BADTKR123"},
                "caller": {"type": "direct"},
            },
        ]

        cleaned = scrub_blocks(captured)

        # Every cleaned block uses only documented input fields.
        for block in cleaned:
            allowed = INPUT_FIELDS_BY_BLOCK_TYPE[block["type"]]
            assert set(block.keys()) <= allowed, (
                f"block {block['type']} carries un-allowlisted fields: "
                f"{set(block.keys()) - allowed}"
            )

        # parsed_output is gone from the text block.
        assert "parsed_output" not in cleaned[1]
        # Everything load-bearing survives.
        assert cleaned[0]["signature"] == "Ep4CClsIDRgC..."
        assert cleaned[1]["text"].startswith("Sure, let me look")
        assert cleaned[1].get("citations") is None
        assert cleaned[2]["input"] == {"ticker": "BADTKR123"}
        assert cleaned[2]["caller"] == {"type": "direct"}
