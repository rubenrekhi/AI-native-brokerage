"""add recurring_investment_executions table

One row per recurring-investment run (executed / skipped_insufficient_funds /
failed). `unique(recurring_investment_id, run_date)` is the engine's
idempotency guard — a retried daily run can't double-record (or, with the
deterministic client_order_id, double-buy). This log is also the data the
future push-notification work reads to tell the user a buy executed or was
skipped.

Revision ID: b2d9f4c1a3e7
Revises: c3a7f1e9b2d4
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = 'b2d9f4c1a3e7'
down_revision = 'c3a7f1e9b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recurring_investment_executions',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column(
            'recurring_investment_id', UUID(as_uuid=True), nullable=False
        ),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('symbol', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('alpaca_order_id', sa.Text(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['recurring_investment_id'],
            ['recurring_investments.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['user_profiles.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'recurring_investment_id',
            'run_date',
            name='uq_recurring_exec_plan_run_date',
        ),
    )
    op.create_index(
        op.f('ix_recurring_investment_executions_recurring_investment_id'),
        'recurring_investment_executions',
        ['recurring_investment_id'],
    )
    op.create_index(
        op.f('ix_recurring_investment_executions_user_id'),
        'recurring_investment_executions',
        ['user_id'],
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_recurring_investment_executions_user_id'),
        table_name='recurring_investment_executions',
    )
    op.drop_index(
        op.f('ix_recurring_investment_executions_recurring_investment_id'),
        table_name='recurring_investment_executions',
    )
    op.drop_table('recurring_investment_executions')
