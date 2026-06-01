"""add pending_actions table

Backs the human-in-the-loop framework (docs/ai/hil-actions.md): one row per
consequential action the AI proposes but must not execute without an explicit
user tap. ``payload`` is run verbatim by the ``action_type`` executor on
confirm; ``preview`` is exactly what the confirmation card showed (audit /
tamper evidence). ``status`` is the written lifecycle (pending → confirmed →
executed/failed, or rejected/superseded); ``expired`` is derived at read time
and never stored. ``ix_pending_actions_conversation_status`` backs the
supersede sweep that cancels live proposals when a new user message arrives.
Rollback drops the table outright.

Revision ID: 7188f3a08573
Revises: e7f1a2b3c4d5
Create Date: 2026-06-01 01:43:35.503885

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '7188f3a08573'
down_revision = 'e7f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('pending_actions',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=False),
    sa.Column('agent_turn_id', sa.UUID(), nullable=True),
    sa.Column('tool_use_id', sa.Text(), nullable=False),
    sa.Column('action_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('preview', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default='pending', nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_turn_id'], ['agent_turns.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user_profiles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pending_actions_action_type'), 'pending_actions', ['action_type'], unique=False)
    op.create_index(op.f('ix_pending_actions_conversation_id'), 'pending_actions', ['conversation_id'], unique=False)
    op.create_index('ix_pending_actions_conversation_status', 'pending_actions', ['conversation_id', 'status'], unique=False)
    op.create_index(op.f('ix_pending_actions_user_id'), 'pending_actions', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_pending_actions_user_id'), table_name='pending_actions')
    op.drop_index('ix_pending_actions_conversation_status', table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_conversation_id'), table_name='pending_actions')
    op.drop_index(op.f('ix_pending_actions_action_type'), table_name='pending_actions')
    op.drop_table('pending_actions')
