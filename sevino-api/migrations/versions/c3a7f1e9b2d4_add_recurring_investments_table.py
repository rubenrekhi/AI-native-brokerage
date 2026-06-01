"""add recurring_investments table

Backs PRD 11.6 recurring investments — one row per user-configured scheduled
buy. The cadence engine (separate change) scans `next_run_date` for due rows,
so `(status, next_run_date)` gets a composite index. `end_condition_kind`
flattens the iOS end-condition tagged union into columns: `never` needs
neither extra column, `on_date` uses `end_on_date`, `after_count` uses
`end_after_count`.

Revision ID: c3a7f1e9b2d4
Revises: 7188f3a08573
Create Date: 2026-06-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = 'c3a7f1e9b2d4'
down_revision = '7188f3a08573'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recurring_investments',
        sa.Column('id', UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.Text(), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('frequency', sa.Text(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column(
            'end_condition_kind',
            sa.Text(),
            nullable=False,
            server_default='never',
        ),
        sa.Column('end_on_date', sa.Date(), nullable=True),
        sa.Column('end_after_count', sa.Integer(), nullable=True),
        sa.Column(
            'executions_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column(
            'status', sa.Text(), nullable=False, server_default='active'
        ),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['user_profiles.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_recurring_investments_user_id'),
        'recurring_investments',
        ['user_id'],
    )
    op.create_index(
        op.f('ix_recurring_investments_next_run_date'),
        'recurring_investments',
        ['next_run_date'],
    )
    op.create_index(
        'ix_recurring_investments_due',
        'recurring_investments',
        ['status', 'next_run_date'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_recurring_investments_due', table_name='recurring_investments'
    )
    op.drop_index(
        op.f('ix_recurring_investments_next_run_date'),
        table_name='recurring_investments',
    )
    op.drop_index(
        op.f('ix_recurring_investments_user_id'),
        table_name='recurring_investments',
    )
    op.drop_table('recurring_investments')
