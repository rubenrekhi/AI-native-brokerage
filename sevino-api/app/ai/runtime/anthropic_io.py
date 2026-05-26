"""Strip SDK-only fields from Anthropic response blocks before re-sending.

The SDK leaks ``parsed_output`` on text blocks (it sets
``__api_exclude__`` but ``model_dump`` ignores that), and the API 400s
when the field re-appears as input. Keep this allowlist in sync with
``docs.claude.com/en/api/messages``.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = ["INPUT_FIELDS_BY_BLOCK_TYPE", "scrub_block", "scrub_blocks"]


# ``cache_control`` is valid on text/tool_use but not thinking.
INPUT_FIELDS_BY_BLOCK_TYPE: Final[dict[str, frozenset[str]]] = {
    "text": frozenset({"type", "text", "citations", "cache_control"}),
    "thinking": frozenset({"type", "thinking", "signature"}),
    "redacted_thinking": frozenset({"type", "data"}),
    "tool_use": frozenset({"type", "id", "name", "input", "caller", "cache_control"}),
}


def scrub_block(block: dict[str, Any]) -> dict[str, Any]:
    # Unknown types pass through so future SDK additions aren't silently dropped.
    block_type = block.get("type")
    allowed = INPUT_FIELDS_BY_BLOCK_TYPE.get(block_type) if block_type else None
    if allowed is None:
        return block
    return {k: v for k, v in block.items() if k in allowed}


def scrub_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [scrub_block(b) for b in blocks]
