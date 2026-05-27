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
    estimate_thinking_tokens,
    scrub_block,
    scrub_blocks,
    to_anthropic_content,
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


class TestToAnthropicContentText:
    def test_passes_text_block_through_with_only_text_field(self):
        # Drops ``block_id`` (Sevino-only iOS-correlation field) — Anthropic
        # 400s on unknown text-block keys.
        converted = to_anthropic_content(
            [
                {
                    "type": "text",
                    "block_id": "01HXYZ",
                    "text": "hello",
                }
            ]
        )
        assert converted == [{"type": "text", "text": "hello"}]

    def test_missing_text_defaults_to_empty_string(self):
        # The loop should never emit a textless block but the helper is
        # defensive — exercise the ``.get("text", "")`` fallback.
        converted = to_anthropic_content([{"type": "text", "block_id": "x"}])
        assert converted == [{"type": "text", "text": ""}]


class TestToAnthropicContentContext:
    # The synthesized wrapper prefix is the model's only signal that the
    # JSON payload is user-supplied modal context. A typo or behavior
    # change here silently corrupts every turn that uses ``user_context``.
    _EXPECTED_PREFIX = (
        "[Attached context from the user's open modal — "
        "use this data to inform your response]\n"
    )

    def test_wraps_context_data_with_attached_prefix(self):
        converted = to_anthropic_content(
            [
                {
                    "type": "context",
                    "block_id": "01HXYZ",
                    "data": {"symbol": "AAPL", "price": "150.00"},
                }
            ]
        )

        assert len(converted) == 1
        assert converted[0]["type"] == "text"
        assert converted[0]["text"].startswith(self._EXPECTED_PREFIX)

    def test_json_encodes_data_payload_compactly(self):
        # ``json.dumps(..., separators=(",", ":"))`` — no whitespace, so
        # cache hits on the prompt prefix line up byte-for-byte across
        # turns.
        converted = to_anthropic_content(
            [
                {
                    "type": "context",
                    "data": {"a": 1, "b": 2},
                }
            ]
        )

        body = converted[0]["text"][len(self._EXPECTED_PREFIX):]
        assert body == '{"a":1,"b":2}'

    def test_non_serializable_values_fall_through_via_default_str(self):
        # ``default=str`` means non-JSON-serializable types (Decimal,
        # datetime, UUID) render via ``str()`` rather than raising.
        import uuid
        from decimal import Decimal

        uid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        converted = to_anthropic_content(
            [
                {
                    "type": "context",
                    "data": {"price": Decimal("150.50"), "id": uid},
                }
            ]
        )

        body = converted[0]["text"][len(self._EXPECTED_PREFIX):]
        assert '"price":"150.50"' in body
        assert f'"id":"{uid}"' in body

    def test_missing_data_field_falls_back_to_empty_dict(self):
        # Defensive — the loop always supplies ``data``, but the helper
        # should not raise if it's absent.
        converted = to_anthropic_content([{"type": "context", "block_id": "x"}])
        body = converted[0]["text"][len(self._EXPECTED_PREFIX):]
        assert body == "{}"

    def test_mixed_text_and_context_preserve_order(self):
        # Reload renders user text + context block in author order. The
        # adapter must not reorder them or the model sees a different
        # narrative.
        converted = to_anthropic_content(
            [
                {"type": "text", "block_id": "a", "text": "what's AAPL?"},
                {"type": "context", "block_id": "b", "data": {"x": 1}},
            ]
        )

        assert len(converted) == 2
        assert converted[0] == {"type": "text", "text": "what's AAPL?"}
        assert converted[1]["type"] == "text"
        assert converted[1]["text"].startswith(self._EXPECTED_PREFIX)


class TestToAnthropicContentDropsUiBlocks:
    # Anthropic 400s on unknown ``type`` values. ``to_anthropic_content``
    # should keep only ``text`` and ``context`` and drop UI-only variants
    # (``status``, ``thinking``, ``stock_card``) before sending history
    # back. Tool-use context is intentionally lost across turns; the
    # assistant text is sufficient continuity.

    def test_drops_status_block(self):
        converted = to_anthropic_content(
            [
                {"type": "text", "text": "hi"},
                {"type": "status", "block_id": "s", "label": "x", "state": "active"},
            ]
        )
        assert converted == [{"type": "text", "text": "hi"}]

    def test_drops_thinking_block(self):
        converted = to_anthropic_content(
            [
                {"type": "thinking", "block_id": "t", "text": "musing"},
                {"type": "text", "text": "answer"},
            ]
        )
        assert converted == [{"type": "text", "text": "answer"}]

    def test_drops_stock_card_block(self):
        converted = to_anthropic_content(
            [
                {"type": "stock_card", "block_id": "sc", "symbol": "AAPL"},
                {"type": "text", "text": "look"},
            ]
        )
        assert converted == [{"type": "text", "text": "look"}]

    def test_drops_tool_use_and_tool_result(self):
        # Anthropic accepts these block types but the loop intentionally
        # drops them — see the docstring comment "Tool-use context is
        # lost across turns; the assistant text is sufficient continuity".
        converted = to_anthropic_content(
            [
                {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                {"type": "text", "text": "final"},
            ]
        )
        assert converted == [{"type": "text", "text": "final"}]

    def test_empty_input_returns_empty_list(self):
        assert to_anthropic_content([]) == []


class TestEstimateThinkingTokens:
    # Heuristic divides total ``thinking`` text characters by 4 — Anthropic
    # doesn't expose per-block token counts. Redacted blocks contribute
    # zero (no plaintext to measure).

    def test_sums_chars_over_four(self):
        blocks = [{"type": "thinking", "thinking": "x" * 100}]
        assert estimate_thinking_tokens(blocks) == 25

    def test_redacted_thinking_contributes_zero(self):
        # The block type is ``redacted_thinking`` (no plaintext field).
        # Even if it carried a "thinking" key, the type filter excludes
        # it from the sum.
        blocks = [{"type": "redacted_thinking", "data": "<encrypted-blob>"}]
        assert estimate_thinking_tokens(blocks) == 0

    def test_redacted_thinking_with_thinking_field_still_zero(self):
        # Defensive: even if a hypothetical SDK leaked a ``thinking`` key
        # onto a redacted block, the type-filter must still exclude it
        # — billing/audit accuracy depends on it.
        blocks = [
            {
                "type": "redacted_thinking",
                "data": "blob",
                "thinking": "should not count",
            }
        ]
        assert estimate_thinking_tokens(blocks) == 0

    def test_none_thinking_treated_as_empty(self):
        blocks = [{"type": "thinking", "thinking": None}]
        assert estimate_thinking_tokens(blocks) == 0

    def test_non_string_thinking_treated_as_empty(self):
        # The ``isinstance(text, str)`` guard prevents type confusion if
        # the SDK ever returned a structured payload here.
        blocks = [{"type": "thinking", "thinking": {"odd": "shape"}}]
        assert estimate_thinking_tokens(blocks) == 0

    def test_sums_across_multiple_blocks(self):
        blocks = [
            {"type": "thinking", "thinking": "x" * 8},
            {"type": "text", "text": "ignored"},
            {"type": "thinking", "thinking": "y" * 12},
        ]
        assert estimate_thinking_tokens(blocks) == 2 + 3

    def test_no_thinking_blocks_returns_zero(self):
        assert estimate_thinking_tokens([{"type": "text", "text": "hi"}]) == 0

    def test_empty_input_returns_zero(self):
        assert estimate_thinking_tokens([]) == 0
