"""Anthropic wire-format helpers.

``scrub_blocks`` strips SDK-only fields from response blocks before
re-sending — the SDK leaks ``parsed_output`` on text blocks (it sets
``__api_exclude__`` but ``model_dump`` ignores that), and the API 400s
when the field re-appears as input. Server-tool result blocks
(``web_search``/``web_fetch``/``code_execution``) are likewise stripped of
output-only fields (e.g. ``caller`` on ``server_tool_use``, per-result
``text``/``citations``) that the API rejects on replay. Keep the
allowlist in sync with ``docs.claude.com/en/api/messages``.

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
    "server_tool_use": frozenset({"type", "id", "name", "input", "cache_control"}),
    "web_search_tool_result": frozenset(
        {"type", "tool_use_id", "content", "cache_control"}
    ),
    "web_fetch_tool_result": frozenset(
        {"type", "tool_use_id", "content", "cache_control"}
    ),
    "code_execution_tool_result": frozenset(
        {"type", "tool_use_id", "content", "cache_control"}
    ),
}

_SERVER_TOOL_RESULT_CONTENT_FIELDS_BY_BLOCK_TYPE: Final[
    dict[str, frozenset[str]]
] = {
    "web_search_result": frozenset(
        {"type", "title", "url", "encrypted_content", "page_age"}
    ),
    "web_search_tool_result_error": frozenset({"type", "error_code"}),
    "web_fetch_result": frozenset({"type", "url", "content", "retrieved_at"}),
    "web_fetch_tool_result_error": frozenset({"type", "error_code"}),
    "code_execution_result": frozenset(
        {"type", "content", "return_code", "stderr", "stdout"}
    ),
    "encrypted_code_execution_result": frozenset(
        {"type", "content", "encrypted_stdout", "return_code", "stderr"}
    ),
    "code_execution_output": frozenset({"type", "file_id"}),
    "code_execution_tool_result_error": frozenset({"type", "error_code"}),
}

_SERVER_TOOL_RESULT_BLOCK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "web_search_tool_result",
        "web_fetch_tool_result",
        "code_execution_tool_result",
    }
)

# Heuristic for the ``thinking_tokens`` audit column — Anthropic gives no
# per-block breakdown. Redacted blocks contribute zero.
_CHARS_PER_TOKEN = 4


def _scrub_server_tool_result_content(value: Any) -> Any:
    if isinstance(value, list):
        return [_scrub_server_tool_result_content(item) for item in value]
    if not isinstance(value, dict):
        return value

    block_type = value.get("type")
    allowed = (
        _SERVER_TOOL_RESULT_CONTENT_FIELDS_BY_BLOCK_TYPE.get(block_type)
        if block_type
        else None
    )
    if allowed is None:
        return {
            k: _scrub_server_tool_result_content(v) for k, v in value.items()
        }
    return {
        k: _scrub_server_tool_result_content(v)
        for k, v in value.items()
        if k in allowed
    }


def scrub_block(block: dict[str, Any]) -> dict[str, Any]:
    # Unknown types pass through so future SDK additions aren't silently dropped.
    block_type = block.get("type")
    allowed = INPUT_FIELDS_BY_BLOCK_TYPE.get(block_type) if block_type else None
    if allowed is None:
        return block
    scrubbed = {k: v for k, v in block.items() if k in allowed}
    if block_type in _SERVER_TOOL_RESULT_BLOCK_TYPES and "content" in scrubbed:
        scrubbed["content"] = _scrub_server_tool_result_content(
            scrubbed["content"]
        )
    return scrubbed


def scrub_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [scrub_block(b) for b in blocks]


def to_anthropic_content(
    content_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep only ``text`` blocks before sending history back to Anthropic.

    Drops the ``block_id`` we add for iOS correlation and every UI-only /
    input-only variant (``status``, ``stock_card``, ``thinking``, ``context``)
    — Anthropic 400s on unknown types. ``context`` is a user attachment that
    is never replayed: the model already saw it as a short hint (the
    attachment's ``render_hint`` in ``app.ai.context_blocks``) on the
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
