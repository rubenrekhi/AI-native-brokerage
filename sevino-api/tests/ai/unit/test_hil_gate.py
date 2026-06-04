"""Unit tests for the HIL runtime gate.

A tool that returns a ``proposal`` must (1) persist a pending_actions row,
(2) emit its confirmation card, and (3) make the loop end the turn
``awaiting_confirmation`` rather than feeding a tool_result back to the model.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from app.ai.blocks import ConfirmationBlock
from app.ai.runtime.dispatch.custom import dispatch_tool_uses
from app.ai.runtime.flow.iteration import _decide_after_response
from app.ai.runtime.types import LoopState
from app.ai.tools.base import (
    ProposedAction,
    Tool,
    ToolContext,
    ToolHttpClients,
    ToolRegistry,
    ToolResult,
)
from app.ai.transport.events import BlockStart

_ACTION_ID = str(uuid.uuid4())


class _ProposingInput(BaseModel):
    pass


class _ProposingTool(Tool[_ProposingInput]):
    name = "propose_thing"
    description = "Proposes a consequential action."
    Input = _ProposingInput

    async def execute(
        self, input: _ProposingInput, ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(
            model_payload={"status": "proposal_presented"},
            ui_block=ConfirmationBlock(
                block_id="blk1",
                action_id=_ACTION_ID,
                kind="transfer",
                title="Confirm deposit",
                rows=[],
            ),
            proposal=ProposedAction(
                action_id=_ACTION_ID,
                action_type="transfer",
                payload={"amount": "10.00"},
            ),
        )


class _RecordingEmitter:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)


@asynccontextmanager
async def _db_factory():
    yield MagicMock()


@pytest.fixture
def patched_repos(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(
        "app.repositories.pending_action.PendingActionRepository.create",
        create,
    )
    monkeypatch.setattr(
        "app.repositories.conversation."
        "ConversationRepository.record_tool_execution",
        AsyncMock(),
    )
    return create


def _tool_use_block():
    return SimpleNamespace(
        type="tool_use", name="propose_thing", id="tu1", input={}
    )


def _registry():
    reg = ToolRegistry()
    reg.register(_ProposingTool())
    return reg


async def test_dispatch_persists_pending_and_emits_card(patched_repos):
    create = patched_repos
    emitter = _RecordingEmitter()

    outcome = await dispatch_tool_uses(
        response_blocks=[_tool_use_block()],
        tool_registry=_registry(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        db_factory=_db_factory,
        sse_emitter=emitter,
        http_clients=ToolHttpClients(),
        invocation_id=uuid.uuid4(),
    )

    assert outcome.proposal_raised is True
    assert outcome.tool_call_count == 1
    create.assert_awaited_once()
    assert str(create.await_args.kwargs["action_id"]) == _ACTION_ID
    assert create.await_args.kwargs["action_type"] == "transfer"
    # The persisted preview is the card the user saw.
    assert create.await_args.kwargs["preview"]["action_id"] == _ACTION_ID

    card_starts = [
        e
        for e in emitter.events
        if isinstance(e, BlockStart)
        and e.block.get("type") == "confirmation"
    ]
    assert len(card_starts) == 1


async def test_dispatch_does_not_persist_when_create_fails(monkeypatch):
    # A persist failure degrades to a tool error: no proposal_raised, no card.
    monkeypatch.setattr(
        "app.repositories.pending_action.PendingActionRepository.create",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr(
        "app.repositories.conversation."
        "ConversationRepository.record_tool_execution",
        AsyncMock(),
    )
    emitter = _RecordingEmitter()

    outcome = await dispatch_tool_uses(
        response_blocks=[_tool_use_block()],
        tool_registry=_registry(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        db_factory=_db_factory,
        sse_emitter=emitter,
        http_clients=ToolHttpClients(),
        invocation_id=uuid.uuid4(),
    )

    assert outcome.proposal_raised is False
    assert outcome.terminal_error_code is not None
    assert not any(
        isinstance(e, BlockStart)
        and e.block.get("type") == "confirmation"
        for e in emitter.events
    )


async def test_dispatch_suppresses_proposal_on_resume(patched_repos):
    # Bug A guard: on a system-initiated resume turn a proposal is dropped — no
    # pending row, no card, no gate — but the model still gets a tool_result so
    # it narrates instead of spinning up another confirmation card.
    create = patched_repos
    emitter = _RecordingEmitter()

    outcome = await dispatch_tool_uses(
        response_blocks=[_tool_use_block()],
        tool_registry=_registry(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        db_factory=_db_factory,
        sse_emitter=emitter,
        http_clients=ToolHttpClients(),
        invocation_id=uuid.uuid4(),
        suppress_proposals=True,
    )

    assert outcome.proposal_raised is False
    create.assert_not_awaited()
    assert not any(
        isinstance(e, BlockStart) and e.block.get("type") == "confirmation"
        for e in emitter.events
    )
    assert len(outcome.tool_result_blocks) == 1


async def test_decide_after_response_does_not_gate_on_resume(patched_repos):
    # With suppress_proposals the resume turn keeps going rather than ending
    # awaiting_confirmation, and appends no confirmation card.
    emitter = _RecordingEmitter()
    response = SimpleNamespace(stop_reason="tool_use", content=[_tool_use_block()])
    messages: list = []
    assistant_blocks: list = []

    outcome = await _decide_after_response(
        response=response,
        invocation_id=uuid.uuid4(),
        state=LoopState(suppress_proposals=True),
        messages=messages,
        assistant_blocks=assistant_blocks,
        tool_registry=_registry(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        db_factory=_db_factory,
        sse_emitter=emitter,
        http_clients=ToolHttpClients(),
    )

    assert outcome.terminal_state != "awaiting_confirmation"
    assert not any(b.get("type") == "confirmation" for b in assistant_blocks)


async def test_decide_after_response_ends_turn_awaiting_confirmation(
    patched_repos,
):
    emitter = _RecordingEmitter()
    response = SimpleNamespace(stop_reason="tool_use", content=[_tool_use_block()])
    messages: list = []
    assistant_blocks: list = []

    outcome = await _decide_after_response(
        response=response,
        invocation_id=uuid.uuid4(),
        state=LoopState(),
        messages=messages,
        assistant_blocks=assistant_blocks,
        tool_registry=_registry(),
        user_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
        db_factory=_db_factory,
        sse_emitter=emitter,
        http_clients=ToolHttpClients(),
    )

    assert outcome.action == "break"
    assert outcome.terminal_state == "awaiting_confirmation"
    assert outcome.error_code is None
    # The turn ends here: no tool_result user message is appended.
    assert messages == []
    # The confirmation card is persisted to the assistant message.
    assert any(b.get("type") == "confirmation" for b in assistant_blocks)
