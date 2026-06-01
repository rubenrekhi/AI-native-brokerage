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


class TestScrubServerToolBlocks:
    def test_strips_output_only_fields_from_server_tool_use(self):
        block = {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "AMD"},
            "caller": {"type": "direct"},
            "cache_control": {"type": "ephemeral"},
        }
        assert scrub_block(block) == {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "AMD"},
            "cache_control": {"type": "ephemeral"},
        }

    def test_strips_dirty_web_search_result_fields(self):
        block = {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "caller": {"type": "direct"},
            "parsed_output": {"sdk": True},
            "content": [
                {
                    "type": "web_search_result",
                    "title": "AMD earnings",
                    "url": "https://example.com/amd",
                    "encrypted_content": "enc",
                    "page_age": None,
                    "text": "output-only summary",
                    "citations": [{"url": "https://example.com/amd"}],
                }
            ],
        }
        assert scrub_block(block) == {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "AMD earnings",
                    "url": "https://example.com/amd",
                    "encrypted_content": "enc",
                    "page_age": None,
                }
            ],
        }

    def test_strips_dirty_web_fetch_error_fields(self):
        block = {
            "type": "web_fetch_tool_result",
            "tool_use_id": "srvtoolu_2",
            "caller": {"type": "direct"},
            "content": {
                "type": "web_fetch_tool_result_error",
                "error_code": "url_not_in_prior_context",
                "text": "not allowed",
                "citations": None,
            },
        }
        assert scrub_block(block) == {
            "type": "web_fetch_tool_result",
            "tool_use_id": "srvtoolu_2",
            "content": {
                "type": "web_fetch_tool_result_error",
                "error_code": "url_not_in_prior_context",
            },
        }

    def test_preserves_code_execution_input_fields_only(self):
        block = {
            "type": "code_execution_tool_result",
            "tool_use_id": "srvtoolu_3",
            "caller": {"type": "direct"},
            "content": {
                "type": "code_execution_result",
                "content": [
                    {
                        "type": "code_execution_output",
                        "file_id": "file_1",
                        "filename": "plot.png",
                    }
                ],
                "return_code": 0,
                "stdout": "ok",
                "stderr": "",
                "parsed_output": None,
            },
        }
        assert scrub_block(block) == {
            "type": "code_execution_tool_result",
            "tool_use_id": "srvtoolu_3",
            "content": {
                "type": "code_execution_result",
                "content": [{"type": "code_execution_output", "file_id": "file_1"}],
                "return_code": 0,
                "stdout": "ok",
                "stderr": "",
            },
        }


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


class TestToAnthropicContentDropsContext:
    # SEV-615: ``context`` is a user attachment, not model history. The
    # model sees it once as a short hint on the turn it arrives (built in
    # ``initialize_turn``); replaying the frozen snapshot on every later turn
    # would be stale and costly, so history reload drops it entirely — same
    # policy as ``status`` / ``stock_card`` / ``thinking``.

    def test_drops_context_block(self):
        converted = to_anthropic_content(
            [
                {
                    "type": "context",
                    "block_id": "01HXYZ",
                    "kind": "portfolio",
                    "data": {"equity": "12500.50"},
                }
            ]
        )
        assert converted == []

    def test_drops_context_keeps_surrounding_text_in_order(self):
        # A reloaded user turn carries ``[text, context]``; only the text
        # survives. The model must not see the frozen ``data`` again.
        converted = to_anthropic_content(
            [
                {"type": "text", "block_id": "a", "text": "what's my portfolio?"},
                {
                    "type": "context",
                    "block_id": "b",
                    "kind": "portfolio",
                    "data": {"equity": "12500.50"},
                },
            ]
        )
        assert converted == [
            {"type": "text", "text": "what's my portfolio?"}
        ]


class TestToAnthropicContentDropsUiBlocks:
    # Anthropic 400s on unknown ``type`` values. ``to_anthropic_content``
    # should keep only ``text`` and drop every other variant (``status``,
    # ``thinking``, ``stock_card``, ``context``) before sending history
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
