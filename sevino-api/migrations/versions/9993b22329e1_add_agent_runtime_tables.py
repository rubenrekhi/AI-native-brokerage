"""add agent runtime tables

Revision ID: 9993b22329e1
Revises: c8d2fa74e103
Create Date: 2026-04-29 00:39:45.351325

Phase 1 schema for the AI agent loop (per docs/ai-v0-plan.md A2.1, D7).

Existing `conversations` and `messages` tables are reshaped in place —
both confirmed empty before this migration runs. `order_events.conversation_id`
FK is preserved.

Three new tables back the agent runtime:
- `agent_turns`: one row per user → assistant turn, with token / cost roll-ups
- `model_invocations`: one row per Anthropic API call within a turn
- `tool_executions`: one row per tool call, with `parent_tool_execution_id`
  self-FK to support nested sub-agent calls from day one

Enum-style columns (`terminal_state`, `agent_role`, `status`) are TEXT, matching
the existing convention (`plaid_items.status`, `ach_relationships.status`) — no
PgEnum is used anywhere in the codebase.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '9993b22329e1'
down_revision = 'c8d2fa74e103'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- ALTER existing (empty) tables ---
    op.drop_column('conversations', 'preview')
    op.drop_column('conversations', 'started_at')

    op.add_column(
        'messages',
        sa.Column(
            'content_blocks',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
    )
    op.drop_column('messages', 'content')
    op.drop_column('messages', 'mcp_cards')
    op.drop_column('messages', 'tool_calls')

    # --- CREATE new agent runtime tables ---
    op.create_table(
        'agent_turns',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('user_message_id', sa.UUID(), nullable=True),
        sa.Column('assistant_message_id', sa.UUID(), nullable=True),
        sa.Column('prompt_hash', sa.Text(), nullable=False),
        sa.Column('model_id', sa.Text(), nullable=False),
        sa.Column('terminal_state', sa.Text(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('error_code', sa.Text(), nullable=True),
        sa.Column('iterations_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_input_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_output_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_cache_read_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_cache_creation_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_thinking_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_cost_usd_micros', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assistant_message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_turns_conversation_id'), 'agent_turns', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_agent_turns_user_id'), 'agent_turns', ['user_id'], unique=False)

    op.create_table(
        'model_invocations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agent_turn_id', sa.UUID(), nullable=False),
        sa.Column('iteration_index', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Text(), nullable=False),
        sa.Column('agent_role', sa.Text(), server_default='main', nullable=False),
        sa.Column('request_system', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('request_messages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('request_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response_content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('stop_reason', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('output_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cache_read_input_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cache_creation_input_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('thinking_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_usd_micros', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_turn_id'], ['agent_turns.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_model_invocations_agent_turn_id'), 'model_invocations', ['agent_turn_id'], unique=False)

    op.create_table(
        'tool_executions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('model_invocation_id', sa.UUID(), nullable=False),
        sa.Column('parent_tool_execution_id', sa.UUID(), nullable=True),
        sa.Column('tool_name', sa.Text(), nullable=False),
        sa.Column('tool_use_id', sa.Text(), nullable=False),
        sa.Column('input_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('output_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('internal_trace', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ui_blocks_emitted', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('upstream_api_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['model_invocation_id'], ['model_invocations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_tool_execution_id'], ['tool_executions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tool_executions_model_invocation_id'), 'tool_executions', ['model_invocation_id'], unique=False)
    op.create_index(op.f('ix_tool_executions_parent_tool_execution_id'), 'tool_executions', ['parent_tool_execution_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tool_executions_parent_tool_execution_id'), table_name='tool_executions')
    op.drop_index(op.f('ix_tool_executions_model_invocation_id'), table_name='tool_executions')
    op.drop_table('tool_executions')

    op.drop_index(op.f('ix_model_invocations_agent_turn_id'), table_name='model_invocations')
    op.drop_table('model_invocations')

    op.drop_index(op.f('ix_agent_turns_user_id'), table_name='agent_turns')
    op.drop_index(op.f('ix_agent_turns_conversation_id'), table_name='agent_turns')
    op.drop_table('agent_turns')

    op.add_column('messages', sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('messages', sa.Column('mcp_cards', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('messages', sa.Column('content', sa.Text(), nullable=True))
    op.drop_column('messages', 'content_blocks')

    op.add_column(
        'conversations',
        sa.Column(
            'started_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    op.add_column('conversations', sa.Column('preview', sa.Text(), nullable=True))
