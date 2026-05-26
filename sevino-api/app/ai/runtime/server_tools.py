"""Server-tool tracking and reconciliation.

Anthropic-hosted server tools (``web_search``, ``web_fetch``,
``code_execution``) stream their ``server_tool_use`` and matching
``*_tool_result`` blocks separately — possibly across iterations. This
module owns the state needed to:

* render and update the status pill for each server-tool call,
* pair uses with results to write durable ``tool_executions`` audit rows,
* flush orphan uses (use without result) at turn end with a failed-state
  audit row + UI pill flip.

The :class:`ServerToolTracker` is turn-scoped — one instance per
:func:`run_agent_turn` call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import sentry_sdk
import structlog
from ulid import ULID

from app.ai.runtime.db import DbSessionFactory
from app.ai.runtime.types import ServerToolsConfig
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import BlockData, BlockEnd, BlockStart
from app.repositories.conversation import ConversationRepository

__all__ = [
    "SERVER_TOOL_RESULT_BLOCK_TYPES",
    "ServerToolTracker",
    "append_status_blocks_for_persistence",
    "build_server_tool_specs",
    "truncate_for_audit",
]

logger = structlog.get_logger(__name__)

_ANTHROPIC_SERVER_TOOL_PREFIX = "anthropic:"

SERVER_TOOL_RESULT_BLOCK_TYPES: frozenset[str] = frozenset(
    {
        "web_search_tool_result",
        "web_fetch_tool_result",
        "code_execution_tool_result",
    }
)

_SERVER_TOOL_STATUS_LABELS: dict[str, str] = {
    "web_search": "Searching the web",
    "web_fetch": "Fetching webpage",
    "code_execution": "Running code",
}


def _server_tool_status_label(name: str | None) -> str:
    if not isinstance(name, str) or not name:
        return "Using tool"
    if name not in _SERVER_TOOL_STATUS_LABELS:
        logger.warning("loop_unknown_server_tool_label", name=name)
    return _SERVER_TOOL_STATUS_LABELS.get(name, f"Using {name}")


def _result_block_status_state(result_block: Any) -> str:
    content = getattr(result_block, "content", None)
    content_type = (
        getattr(content, "type", None) if content is not None else None
    )
    if isinstance(content_type, str) and content_type.endswith("_error"):
        return "failed"
    return "complete"


def build_server_tool_specs(config: ServerToolsConfig) -> list[dict[str, Any]]:
    # ``type`` is Anthropic's date-suffixed version pin. Bumping it opts
    # into behavior changes — coordinate with the matching SDK Param type.
    specs: list[dict[str, Any]] = []
    if config.web_search_enabled:
        specs.append(
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": config.web_search_max_uses,
            }
        )
    if config.web_fetch_enabled:
        specs.append(
            {
                "type": "web_fetch_20250910",
                "name": "web_fetch",
                "max_uses": config.web_fetch_max_uses,
            }
        )
    if config.code_execution_enabled:
        specs.append(
            {
                "type": "code_execution_20250825",
                "name": "code_execution",
            }
        )
    return specs


def truncate_for_audit(value: Any, max_chars: int = 2000) -> Any:
    """Clip oversize payloads for the audit row.

    ``_preview`` is debug-only, never JSON-parsed downstream.
    """
    try:
        encoded = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return {"_audit_error": "non_json_payload"}
    if len(encoded) <= max_chars:
        return value
    return {"_truncated": True, "_preview": encoded[:max_chars]}


def append_status_blocks_for_persistence(
    *,
    tool_use_ids: list[str],
    status_block_records: dict[str, dict[str, Any]],
    status_blocks_persisted: set[str],
    assistant_blocks: list[dict[str, Any]],
) -> None:
    """Append unpersisted status-pill records to ``assistant_blocks``.

    Dedups against ``status_blocks_persisted`` so multi-iteration tool use
    isn't appended twice.
    """
    for tool_use_id in tool_use_ids:
        if tool_use_id in status_blocks_persisted:
            continue
        record = status_block_records.get(tool_use_id)
        if record is None:
            continue
        assistant_blocks.append(record)
        status_blocks_persisted.add(tool_use_id)


def _capture_loop_warning(
    name: str,
    *,
    turn_id: uuid.UUID,
    conversation_id: uuid.UUID,
    extra_tags: dict[str, str] | None = None,
) -> None:
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("turn_id", str(turn_id))
        scope.set_tag("conversation_id", str(conversation_id))
        if extra_tags:
            for k, v in extra_tags.items():
                scope.set_tag(k, v)
        sentry_sdk.capture_message(name, level="warning")


class ServerToolTracker:
    """Pair server-tool uses with their results across iterations.

    A use can be emitted in one iteration and its result in the next.
    ``open_status_blocks`` and ``status_block_records`` track the UI pill;
    ``pending_server_tool_uses`` tracks audit rows yet to be written.
    Orphans left at turn end are flushed by :meth:`flush_orphans`.
    """

    def __init__(self) -> None:
        self.open_status_blocks: dict[str, str] = {}
        self.status_block_records: dict[str, dict[str, Any]] = {}
        self.status_blocks_persisted: set[str] = set()
        self.pending_server_tool_uses: dict[str, dict[str, Any]] = {}

    async def on_use_started(
        self,
        *,
        tool_use_id: str,
        raw_name: Any,
        sse_emitter: SSEEmitter,
    ) -> None:
        status_block_id = str(ULID())
        self.open_status_blocks[tool_use_id] = status_block_id
        record: dict[str, Any] = {
            "type": "status",
            "block_id": status_block_id,
            "label": _server_tool_status_label(raw_name),
            "state": "active",
        }
        self.status_block_records[tool_use_id] = record
        await sse_emitter.emit(BlockStart(block=record))

    async def on_result_received(
        self,
        *,
        tool_use_id: str,
        result_block: Any,
        sse_emitter: SSEEmitter,
    ) -> None:
        status_block_id = self.open_status_blocks.pop(tool_use_id, None)
        if status_block_id is None:
            return
        new_state = _result_block_status_state(result_block)
        await sse_emitter.emit(
            BlockData(block_id=status_block_id, data={"state": new_state})
        )
        await sse_emitter.emit(BlockEnd(block_id=status_block_id))
        self.status_block_records[tool_use_id]["state"] = new_state

    def mark_active_failed(self) -> None:
        """Flip active pills in-place on cancellation.

        The records dict shares refs with ``assistant_blocks`` so a reload
        shows failed pills, not phantom spinners.
        """
        for record in self.status_block_records.values():
            if record.get("state") == "active":
                record["state"] = "failed"

    async def record_executions(
        self,
        *,
        response_blocks: list[Any],
        invocation_id: uuid.UUID,
        db_factory: DbSessionFactory,
        turn_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> None:
        """Pair server-tool uses with their results from one iteration.

        Anthropic may emit the use in one iteration and its result in the
        next. Orphans left at turn end are flushed by :meth:`flush_orphans`.
        """
        if not response_blocks:
            return

        for block in response_blocks:
            if getattr(block, "type", None) != "server_tool_use":
                continue
            tool_use_id = getattr(block, "id", "") or ""
            raw_name = getattr(block, "name", "") or ""
            if not tool_use_id or tool_use_id in self.pending_server_tool_uses:
                continue
            raw_input = getattr(block, "input", None)
            self.pending_server_tool_uses[tool_use_id] = {
                "tool_name": f"{_ANTHROPIC_SERVER_TOOL_PREFIX}{raw_name}",
                "input_payload": raw_input if isinstance(raw_input, dict) else {},
            }

        for block in response_blocks:
            block_type = getattr(block, "type", None)
            if block_type not in SERVER_TOOL_RESULT_BLOCK_TYPES:
                continue
            tool_use_id = getattr(block, "tool_use_id", None)
            if not isinstance(tool_use_id, str) or not tool_use_id:
                continue
            use_info = self.pending_server_tool_uses.pop(tool_use_id, None)
            if use_info is None:
                logger.warning(
                    "loop_server_tool_orphan_result", tool_use_id=tool_use_id
                )
                _capture_loop_warning(
                    "loop_server_tool_orphan_result",
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    extra_tags={"tool_use_id": tool_use_id},
                )
                continue

            content = getattr(block, "content", None)
            content_type = (
                getattr(content, "type", None) if content is not None else None
            )
            is_error = isinstance(content_type, str) and content_type.endswith(
                "_error"
            )
            try:
                if hasattr(content, "model_dump"):
                    dumped_content = content.model_dump(mode="json")
                elif isinstance(content, list):
                    # Round-trip Pydantic items via model_dump — otherwise
                    # ``json.dumps(default=str)`` would store repr strings.
                    dumped_content = [
                        item.model_dump(mode="json")
                        if hasattr(item, "model_dump")
                        else item
                        for item in content
                    ]
                else:
                    dumped_content = content
            except Exception:
                logger.exception(
                    "loop_server_tool_content_dump_failed",
                    tool_name=use_info["tool_name"],
                    tool_use_id=tool_use_id,
                )
                _capture_loop_warning(
                    "loop_server_tool_content_dump_failed",
                    turn_id=turn_id,
                    conversation_id=conversation_id,
                    extra_tags={
                        "tool_use_id": tool_use_id,
                        "tool_name": use_info["tool_name"],
                    },
                )
                dumped_content = {"_dump_failed": True}

            if is_error:
                status = "error"
                error_code = (
                    getattr(content, "error_code", None)
                    if content is not None
                    else None
                )
                error_message = (
                    str(error_code) if error_code is not None else "unknown_error"
                )
                output_payload: dict[str, Any] | None = None
            else:
                status = "success"
                error_message = None
                output_payload = {"content": truncate_for_audit(dumped_content)}

            async with db_factory() as db:
                await ConversationRepository.record_tool_execution(
                    db,
                    model_invocation_id=invocation_id,
                    tool_name=use_info["tool_name"],
                    tool_use_id=tool_use_id,
                    input_payload=use_info["input_payload"],
                    status=status,
                    output_payload=output_payload,
                    error_message=error_message,
                )

    async def flush_orphans(
        self,
        *,
        invocation_id: uuid.UUID | None,
        db_factory: DbSessionFactory,
        sse_emitter: SSEEmitter,
        turn_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> None:
        """Close server-tool uses that never got a matching result.

        Anything still in ``pending_server_tool_uses`` is a contract
        violation or an early-ending turn. Emits a failed-state
        ``BlockData`` + ``BlockEnd`` for each orphan pill and writes a
        ``status=error`` audit row.
        """
        for tool_use_id, use_info in list(self.pending_server_tool_uses.items()):
            logger.warning(
                "loop_server_tool_missing_result_block",
                tool_name=use_info["tool_name"],
                tool_use_id=tool_use_id,
            )
            _capture_loop_warning(
                "loop_server_tool_missing_result_block",
                turn_id=turn_id,
                conversation_id=conversation_id,
                extra_tags={
                    "tool_use_id": tool_use_id,
                    "tool_name": use_info["tool_name"],
                },
            )

            status_block_id = self.open_status_blocks.pop(tool_use_id, None)
            if status_block_id is not None:
                await sse_emitter.emit(
                    BlockData(block_id=status_block_id, data={"state": "failed"})
                )
                await sse_emitter.emit(BlockEnd(block_id=status_block_id))
                if tool_use_id in self.status_block_records:
                    self.status_block_records[tool_use_id]["state"] = "failed"

            if invocation_id is not None:
                async with db_factory() as db:
                    await ConversationRepository.record_tool_execution(
                        db,
                        model_invocation_id=invocation_id,
                        tool_name=use_info["tool_name"],
                        tool_use_id=tool_use_id,
                        input_payload=use_info["input_payload"],
                        status="error",
                        output_payload=None,
                        error_message="missing_result_block",
                    )

        self.pending_server_tool_uses.clear()
