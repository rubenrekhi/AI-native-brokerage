"""Helpers for round-tripping Anthropic message content.

The Anthropic Python SDK's response models can carry SDK-only fields that
the API accepts on *output* but rejects when echoed back as *input* on the
next iteration. The canonical offender is ``parsed_output`` on text blocks
— the SDK's ``ParsedTextBlock`` declares
``__api_exclude__ = {"parsed_output"}`` (see
``anthropic/types/parsed_message.py``) but ``model_dump(mode="json")`` does
not honor that marker, so the field leaks into the dict the loop appends
to ``messages``. Anthropic 400s:

  messages.N.content.M.text.parsed_output: Extra inputs are not permitted

The loop must scrub before:
  * appending the response to its rolling ``messages`` list, and
  * persisting it to ``model_invocations.response_content`` (the
    source-of-truth replayed on subsequent turns and audit reads).

Allowlist semantics: per block type, keep every field documented as valid
in the Anthropic Messages API request body for assistant content. Verified
against the public spec at
``docs.claude.com/en/api/messages``; if Anthropic adds new valid input
fields the allowlist must be updated (catch via integration smoke). Unknown
``type`` values pass through untouched so a future SDK addition is not
silently dropped — the worst case is the same 400 we're fixing now,
which a smoke test will catch.

Only fields with no documented input role are filtered. As of SDK 0.97.0
that is just ``parsed_output``; everything else the SDK emits on a content
block is also a valid input field per the spec.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = ["INPUT_FIELDS_BY_BLOCK_TYPE", "scrub_block", "scrub_blocks"]


# Allowlist of fields each assistant-content block accepts as input on the
# Messages API. Sourced from the public spec; keep this list in sync with
# ``docs.claude.com/en/api/messages`` whenever the SDK is upgraded.
#
# - ``cache_control`` is valid on text and tool_use; thinking blocks do
#   NOT accept it (per spec).
# - ``citations`` is a valid optional input on text blocks (a list of
#   ``TextCitationParam``); null and absent are equivalent.
# - ``caller`` is a valid optional input on tool_use blocks (Direct /
#   ServerToolCaller union).
INPUT_FIELDS_BY_BLOCK_TYPE: Final[dict[str, frozenset[str]]] = {
    "text": frozenset({"type", "text", "citations", "cache_control"}),
    "thinking": frozenset({"type", "thinking", "signature"}),
    "redacted_thinking": frozenset({"type", "data"}),
    "tool_use": frozenset({"type", "id", "name", "input", "caller", "cache_control"}),
}


def scrub_block(block: dict[str, Any]) -> dict[str, Any]:
    """Strip SDK-only fields from one assistant content block.

    Returns a new dict containing only the fields valid as Anthropic API
    input for the block's ``type``. If ``type`` is missing or unknown the
    block is returned unchanged so future SDK additions are not silently
    dropped.
    """
    block_type = block.get("type")
    allowed = INPUT_FIELDS_BY_BLOCK_TYPE.get(block_type) if block_type else None
    if allowed is None:
        return block
    return {k: v for k, v in block.items() if k in allowed}


def scrub_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply :func:`scrub_block` to every block in ``blocks``."""
    return [scrub_block(b) for b in blocks]
