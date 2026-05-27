"""Unit tests for ``app.ai.runtime.dispatch.server``.

Covers two surfaces with documented gaps:

1. ``truncate_for_audit`` — the defensive non-JSON and oversize-payload
   branches. Operators read audit rows; an unexpected shape here breaks
   triage flows. Direct unit tests pin the return shape without
   piping through the loop.

2. ``ServerToolTracker.flush_orphans`` with ``invocation_id=None`` — the
   path that fires when the loop never completed a successful model
   invocation but did emit a server_tool_use during streaming. The
   contract is "emit SSE failed-state but skip the audit row" — without
   this test, the iOS/DB asymmetry could silently flip either way.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.ai.runtime.dispatch.server import (
    ServerToolTracker,
    truncate_for_audit,
)
from app.ai.transport.emitter import SSEEmitter
from app.ai.transport.events import BlockData, BlockEnd, Event


# ---------- truncate_for_audit ----------


class TestTruncateForAuditPassThrough:
    def test_small_value_returned_unchanged(self) -> None:
        # The dominant path: payload encodes to less than max_chars.
        # The function returns the *original* value so downstream JSONB
        # storage sees the typed payload, not a re-encoded string.
        value = {"symbol": "AAPL", "price": "150.00"}
        assert truncate_for_audit(value) is value

    def test_at_max_chars_boundary_returned_unchanged(self) -> None:
        # ``<= max_chars`` is the boundary — a payload exactly at the
        # limit must pass through. Off-by-one regression guard.
        # We craft a value whose JSON encoding is exactly 10 chars
        # (``"x" * 8`` quoted → 10 chars).
        value = "x" * 8
        assert truncate_for_audit(value, max_chars=10) is value

    def test_decimal_default_str_succeeds_in_pass_through(self) -> None:
        # ``default=str`` lets non-JSON-serializable types (Decimal,
        # datetime, UUID) encode successfully — so the function returns
        # the original value, not the audit_error shape.
        from decimal import Decimal

        value = {"price": Decimal("150.50")}
        assert truncate_for_audit(value) is value


class TestTruncateForAuditOversize:
    def test_oversize_returns_truncated_dict_with_preview(self) -> None:
        # When encoded length > max_chars, the function returns the
        # canonical ``{"_truncated": True, "_preview": ...}`` shape.
        # Operators reading audit rows rely on these exact keys.
        value = "y" * 5000  # encodes to ~5002 chars
        result = truncate_for_audit(value, max_chars=100)

        assert isinstance(result, dict)
        assert result["_truncated"] is True
        # ``_preview`` is the first ``max_chars`` of the JSON encoding,
        # not the raw value — so a leading quote character is expected.
        assert isinstance(result["_preview"], str)
        assert len(result["_preview"]) == 100
        assert result["_preview"].startswith('"y')

    def test_default_max_chars_is_2000(self) -> None:
        # Lock the default so a regression that drops the kwarg
        # silently doesn't pass a different limit.
        small = "y" * 1900
        assert truncate_for_audit(small) is small  # ~1902 chars, under

        large = "y" * 2100
        result = truncate_for_audit(large)
        assert isinstance(result, dict)
        assert result["_truncated"] is True

    def test_oversize_list_returns_truncated_shape(self) -> None:
        # The branch fires on any encoded representation — list payloads
        # are common (server_tool_use input arrays) and must trigger the
        # same shape.
        value = ["item"] * 1000  # encodes to ~9000 chars
        result = truncate_for_audit(value, max_chars=50)

        assert result["_truncated"] is True
        assert result["_preview"].startswith('["item"')


class TestTruncateForAuditNonJsonPayload:
    def test_non_serializable_dict_key_returns_audit_error(self) -> None:
        # ``json.dumps`` raises ``TypeError`` for non-str/int/float/bool
        # dict keys even with ``default=str``. The function catches this
        # and returns the canonical audit_error shape — operators get a
        # signal instead of a silent crash.
        value = {object(): "x"}
        result = truncate_for_audit(value)

        assert result == {"_audit_error": "non_json_payload"}

    def test_non_serializable_does_not_raise(self) -> None:
        # Defensive: a malformed payload must NOT propagate the
        # exception. If the function ever stops catching, audit writes
        # would crash the iteration. Pins the no-raise contract.
        try:
            truncate_for_audit({object(): "x"})
        except (TypeError, ValueError):
            pytest.fail(
                "truncate_for_audit must not propagate JSON encoding errors"
            )


# ---------- ServerToolTracker.flush_orphans with invocation_id=None ----------


@dataclass
class _StubSession:
    pass


def _make_db_factory() -> Any:
    @asynccontextmanager
    async def factory():
        yield _StubSession()

    return factory


async def _drain(emitter: SSEEmitter) -> list[Event]:
    events: list[Event] = []
    async for event in emitter.iter_events():
        events.append(event)
    return events


class TestFlushOrphansNoInvocation:
    # When a server_tool_use was streamed (pill went active on the wire)
    # but the iteration never completed a model invocation —
    # ``last_invocation_id`` is ``None``. The orphan flush must still
    # close the pill on the wire (iOS would otherwise spin forever) but
    # must skip the audit write (no row to FK-link the tool_execution
    # to). This asymmetry between SSE and DB is the documented behavior;
    # any regression that breaks the symmetry should fail here.

    async def test_emits_failed_state_sse_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracker = ServerToolTracker()
        # Pre-seed the tracker as if a server_tool_use streamed first.
        tracker.pending_server_tool_uses["srvtoolu_1"] = {
            "tool_name": "anthropic:web_search",
            "input_payload": {"query": "amd news"},
        }
        tracker.open_status_blocks["srvtoolu_1"] = "block_id_1"
        tracker.status_block_records["srvtoolu_1"] = {
            "type": "status",
            "block_id": "block_id_1",
            "label": "Searching the web",
            "state": "active",
        }

        record_mock = AsyncMock()
        monkeypatch.setattr(
            "app.ai.runtime.dispatch.server.ConversationRepository.record_tool_execution",
            record_mock,
        )

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        await tracker.flush_orphans(
            invocation_id=None,
            db_factory=_make_db_factory(),
            sse_emitter=emitter,
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
        )

        await emitter.close()
        events = await drain_task

        # iOS sees the pill flip to failed and close — no phantom spinner.
        data_events = [e for e in events if isinstance(e, BlockData)]
        end_events = [e for e in events if isinstance(e, BlockEnd)]
        assert len(data_events) == 1
        assert data_events[0].block_id == "block_id_1"
        assert data_events[0].data == {"state": "failed"}
        assert len(end_events) == 1
        assert end_events[0].block_id == "block_id_1"

    async def test_skips_audit_write_when_invocation_id_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The "skip audit when invocation_id is None" branch.
        # ``record_tool_execution`` MUST NOT be called — there's no
        # ``agent_turn`` row to FK-link to.
        tracker = ServerToolTracker()
        tracker.pending_server_tool_uses["srvtoolu_1"] = {
            "tool_name": "anthropic:web_search",
            "input_payload": {"query": "amd"},
        }

        record_mock = AsyncMock()
        monkeypatch.setattr(
            "app.ai.runtime.dispatch.server.ConversationRepository.record_tool_execution",
            record_mock,
        )

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        await tracker.flush_orphans(
            invocation_id=None,
            db_factory=_make_db_factory(),
            sse_emitter=emitter,
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
        )

        await emitter.close()
        await drain_task

        record_mock.assert_not_awaited()

    async def test_writes_audit_row_when_invocation_id_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The symmetric case — when ``invocation_id`` IS set, the audit
        # write MUST happen. This is the contrast that makes the
        # ``None`` branch meaningful; without this companion test, a
        # regression that always skips would pass.
        tracker = ServerToolTracker()
        tracker.pending_server_tool_uses["srvtoolu_1"] = {
            "tool_name": "anthropic:web_search",
            "input_payload": {"query": "amd"},
        }
        tracker.open_status_blocks["srvtoolu_1"] = "block_id_1"
        tracker.status_block_records["srvtoolu_1"] = {
            "type": "status",
            "block_id": "block_id_1",
            "label": "Searching the web",
            "state": "active",
        }

        record_mock = AsyncMock()
        monkeypatch.setattr(
            "app.ai.runtime.dispatch.server.ConversationRepository.record_tool_execution",
            record_mock,
        )

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        invocation_id = uuid.uuid4()
        await tracker.flush_orphans(
            invocation_id=invocation_id,
            db_factory=_make_db_factory(),
            sse_emitter=emitter,
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
        )

        await emitter.close()
        await drain_task

        record_mock.assert_awaited_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["model_invocation_id"] == invocation_id
        assert kwargs["status"] == "error"
        assert kwargs["error_message"] == "missing_result_block"
        assert kwargs["tool_name"] == "anthropic:web_search"

    async def test_clears_pending_after_flush(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``pending_server_tool_uses`` must be empty post-flush so a
        # subsequent ``record_executions`` call doesn't try to re-process
        # the orphan. The state mutation is part of the contract.
        tracker = ServerToolTracker()
        tracker.pending_server_tool_uses["srvtoolu_1"] = {
            "tool_name": "anthropic:web_search",
            "input_payload": {},
        }

        monkeypatch.setattr(
            "app.ai.runtime.dispatch.server.ConversationRepository.record_tool_execution",
            AsyncMock(),
        )

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        await tracker.flush_orphans(
            invocation_id=None,
            db_factory=_make_db_factory(),
            sse_emitter=emitter,
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
        )

        await emitter.close()
        await drain_task

        assert tracker.pending_server_tool_uses == {}

    async def test_flips_records_state_to_failed_for_persistence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``status_block_records`` shares dict refs with the assistant
        # message blocks. Flipping its ``state`` to "failed" must happen
        # in-place so the persisted message reflects the same final
        # state iOS saw. Without this, a reload would show "active"
        # pills that never resolve.
        tracker = ServerToolTracker()
        tracker.pending_server_tool_uses["srvtoolu_1"] = {
            "tool_name": "anthropic:web_search",
            "input_payload": {},
        }
        tracker.open_status_blocks["srvtoolu_1"] = "block_id_1"
        record = {
            "type": "status",
            "block_id": "block_id_1",
            "label": "Searching the web",
            "state": "active",
        }
        tracker.status_block_records["srvtoolu_1"] = record

        monkeypatch.setattr(
            "app.ai.runtime.dispatch.server.ConversationRepository.record_tool_execution",
            AsyncMock(),
        )

        emitter = SSEEmitter()
        drain_task = asyncio.create_task(_drain(emitter))

        await tracker.flush_orphans(
            invocation_id=None,
            db_factory=_make_db_factory(),
            sse_emitter=emitter,
            turn_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
        )

        await emitter.close()
        await drain_task

        # The same record object was mutated — identity check, not just
        # value, so a regression that deep-copies before mutating fails.
        assert tracker.status_block_records["srvtoolu_1"] is record
        assert record["state"] == "failed"
