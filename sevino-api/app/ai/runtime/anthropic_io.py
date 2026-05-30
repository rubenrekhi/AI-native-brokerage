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

import json
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
    """Strip Sevino-only fields before sending history back to Anthropic.

    Drops the ``block_id`` we add for iOS correlation and UI-only variants
    (``status``, ``stock_card``, ``thinking``) — Anthropic 400s on unknown
    types. Tool-use context is lost across turns; the assistant text is
    sufficient continuity.
    """
    converted: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.get("type") == "text":
            converted.append({"type": "text", "text": block.get("text", "")})
        elif block.get("type") == "context":
            data = block.get("data", {})
            converted.append(
                {
                    "type": "text",
                    "text": (
                        "[Attached context from the user's open modal — "
                        "use this data to inform your response]\n"
                        + json.dumps(data, separators=(",", ":"), default=str)
                    ),
                }
            )
    return converted


def estimate_thinking_tokens(response_content: list[dict[str, Any]]) -> int:
    total = 0
    for block in response_content:
        if block.get("type") == "thinking":
            text = block.get("thinking") or ""
            if isinstance(text, str):
                total += len(text) // _CHARS_PER_TOKEN
    return total
