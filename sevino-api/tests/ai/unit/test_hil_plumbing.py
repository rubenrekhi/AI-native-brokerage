"""Unit tests for the human-in-the-loop plumbing primitives."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.ai.blocks import BlockAdapter, ConfirmationBlock, ConfirmationRow
from app.ai.tools.base import ProposedAction, ToolResult
from app.models.pending_action import PendingActionStatus, effective_status
from app.routes.conversations import _overlay_confirmation_status

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_confirmation_block_roundtrips_through_block_union():
    cb = ConfirmationBlock(
        block_id="b1",
        action_id="a1",
        kind="transfer",
        title="Confirm deposit",
        rows=[ConfirmationRow(label="Amount", value="$10.00")],
        details={"direction": "INCOMING"},
    )
    decoded = BlockAdapter.validate_python(cb.model_dump(mode="json"))
    assert isinstance(decoded, ConfirmationBlock)
    assert decoded.status == "pending"
    assert decoded.hold_to_confirm is True
    assert decoded.rows[0].label == "Amount"
    assert decoded.details == {"direction": "INCOMING"}


def test_proposed_action_defaults_and_attaches_to_tool_result():
    pa = ProposedAction(
        action_id="a1", action_type="transfer", payload={"amount": "10.00"}
    )
    assert pa.expires_in_s == 300
    result = ToolResult(model_payload={"ok": True}, proposal=pa)
    assert result.proposal is pa


def test_tool_result_has_no_proposal_by_default():
    assert ToolResult(model_payload={}).proposal is None


class TestEffectiveStatus:
    def test_pending_past_expiry_is_expired(self):
        assert (
            effective_status(
                PendingActionStatus.PENDING,
                _NOW - timedelta(seconds=1),
                now=_NOW,
            )
            == PendingActionStatus.EXPIRED
        )

    def test_pending_before_expiry_stays_pending(self):
        assert (
            effective_status(
                PendingActionStatus.PENDING,
                _NOW + timedelta(seconds=60),
                now=_NOW,
            )
            == PendingActionStatus.PENDING
        )

    @pytest.mark.parametrize(
        "status",
        ["confirmed", "rejected", "superseded", "executed", "failed"],
    )
    def test_written_states_never_derive_to_expired(self, status):
        # Even long past the window, a written terminal state is authoritative.
        assert (
            effective_status(status, _NOW - timedelta(days=7), now=_NOW)
            == status
        )


class TestOverlayConfirmationStatus:
    def test_overlays_resolved_status_without_mutating_input(self):
        action_id = uuid.uuid4()
        blocks = [
            {"type": "text", "block_id": "t1", "text": "hi"},
            {
                "type": "confirmation",
                "block_id": "c1",
                "action_id": str(action_id),
                "status": "pending",
            },
        ]
        out = _overlay_confirmation_status(blocks, {action_id: "executed"})
        assert out[1]["status"] == "executed"
        # Non-confirmation block passes through unchanged.
        assert out[0] is blocks[0]
        # Original confirmation dict is not mutated.
        assert blocks[1]["status"] == "pending"

    def test_unresolved_action_id_left_untouched(self):
        blocks = [
            {
                "type": "confirmation",
                "action_id": str(uuid.uuid4()),
                "status": "pending",
            }
        ]
        # Some other action resolved, not this one.
        out = _overlay_confirmation_status(blocks, {uuid.uuid4(): "executed"})
        assert out[0]["status"] == "pending"

    def test_empty_statuses_returns_input_unchanged(self):
        blocks = [{"type": "confirmation", "action_id": "x"}]
        assert _overlay_confirmation_status(blocks, {}) is blocks
