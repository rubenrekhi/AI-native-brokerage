"""Unit tests for the agent-runtime ORM models.

Acceptance criteria from SEV-470 / A2.2:
- Models import without circular-import errors.
- ``app.models`` re-exports all three.
- Relationship navigation (``turn.invocations``, ``invocation.tool_executions``)
  works in a unit test.
"""

import uuid

from sqlalchemy.orm import configure_mappers

from app.models import AgentTurn, ModelInvocation, ToolExecution


def test_models_re_exported_from_app_models():
    import app.models as models

    assert models.AgentTurn is AgentTurn
    assert models.ModelInvocation is ModelInvocation
    assert models.ToolExecution is ToolExecution
    for name in ("AgentTurn", "ModelInvocation", "ToolExecution"):
        assert name in models.__all__


def test_relationships_configure_without_errors():
    # Forces SQLAlchemy to resolve every relationship() — catches mistakes
    # like a wrong back_populates or missing foreign_keys= at import time
    # rather than at first DB use.
    configure_mappers()


def test_agent_turn_invocations_relationship():
    turn = AgentTurn(
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        prompt_hash="hash",
        model_id="claude-sonnet-4-6",
    )
    invocation_a = ModelInvocation(
        iteration_index=0,
        model_id="claude-sonnet-4-6",
        request_system=[],
        request_messages=[],
    )
    invocation_b = ModelInvocation(
        iteration_index=1,
        model_id="claude-sonnet-4-6",
        request_system=[],
        request_messages=[],
    )
    turn.invocations.append(invocation_a)
    turn.invocations.append(invocation_b)

    assert turn.invocations == [invocation_a, invocation_b]
    assert invocation_a.agent_turn is turn
    assert invocation_b.agent_turn is turn


def test_model_invocation_tool_executions_relationship():
    invocation = ModelInvocation(
        iteration_index=0,
        model_id="claude-sonnet-4-6",
        request_system=[],
        request_messages=[],
    )
    tool_exec = ToolExecution(
        tool_name="get_stock_info",
        tool_use_id="toolu_abc",
        input_payload={"symbol": "AMD"},
        status="success",
    )
    invocation.tool_executions.append(tool_exec)

    assert invocation.tool_executions == [tool_exec]
    assert tool_exec.model_invocation is invocation


def test_tool_execution_self_referential_parent_child():
    parent = ToolExecution(
        tool_name="propose_trade",
        tool_use_id="toolu_parent",
        input_payload={},
        status="success",
    )
    child = ToolExecution(
        tool_name="get_stock_info",
        tool_use_id="toolu_child",
        input_payload={"symbol": "AMD"},
        status="success",
    )
    parent.children.append(child)

    assert parent.children == [child]
    assert child.parent is parent
