"""Anthropic wire-format helpers.

``scrub_blocks`` strips SDK-only fields from response blocks before
re-sending — the SDK leaks ``parsed_output`` on text blocks (it sets
``__api_exclude__`` but ``model_dump`` ignores that), and the API 400s
when the field re-appears as input. Keep the allowlist in sync with
``docs.claude.com/en/api/messages``.

``to_anthropic_content`` adapts Sevino's persisted block shapes back to
Anthropic input format. ``estimate_thinking_tokens`` is a heuristic for
the ``thinking_tokens`` audit column.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "INPUT_FIELDS_BY_BLOCK_TYPE",
    "estimate_thinking_tokens",
    "scrub_block",
    "scrub_blocks",
    "to_anthropic_content",
]


# ``cache_control`` is valid on text/tool_use but not thinking.
INPUT_FIELDS_BY_BLOCK_TYPE: Final[dict[str, frozenset[str]]] = {
    "text": frozenset({"type", "text", "citations", "cache_control"}),
    "thinking": frozenset({"type", "thinking", "signature"}),
    "redacted_thinking": frozenset({"type", "data"}),
    "tool_use": frozenset({"type", "id", "name", "input", "caller", "cache_control"}),
}

# Heuristic for the ``thinking_tokens`` audit column — Anthropic gives no
# per-block breakdown. Redacted blocks contribute zero.
_CHARS_PER_TOKEN = 4


def scrub_block(block: dict[str, Any]) -> dict[str, Any]:
    # Unknown types pass through so future SDK additions aren't silently dropped.
    block_type = block.get("type")
    allowed = INPUT_FIELDS_BY_BLOCK_TYPE.get(block_type) if block_type else None
    if allowed is None:
        return block
    return {k: v for k, v in block.items() if k in allowed}


def scrub_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [scrub_block(b) for b in blocks]


def to_anthropic_content(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only ``text`` blocks before sending history back to Anthropic.

    Drops the ``block_id`` we add for iOS correlation and every UI-only /
    input-only variant (``status``, ``stock_card``, ``thinking``, ``context``)
    — Anthropic 400s on unknown types. ``context`` is a user attachment that
    is never replayed: the model already saw it as a short ``kind``-only
    hint (the attachment's ``render_hint`` in ``app.ai.context_blocks``) on the
    turn it arrived, so re-sending the frozen snapshot every later turn would
    be stale and costly (SEV-615). Tool-use context is also lost across turns;
    the assistant text is sufficient continuity.
    """
    return [
        {"type": "text", "text": block.get("text", "")}
        for block in content_blocks
        if block.get("type") == "text"
    ]


def estimate_thinking_tokens(response_content: list[dict[str, Any]]) -> int:
    total = 0
    for block in response_content:
        if block.get("type") == "thinking":
            text = block.get("thinking") or ""
            if isinstance(text, str):
                total += len(text) // _CHARS_PER_TOKEN
    return total
