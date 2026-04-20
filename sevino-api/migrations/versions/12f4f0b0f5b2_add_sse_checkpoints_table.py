"""add sse_checkpoints table

Revision ID: 12f4f0b0f5b2
Revises: 339563b12284
Create Date: 2026-04-20 19:25:46.101432

Process-level checkpoint store for long-running SSE listeners. One row
per stream; `last_event_id` is what we pass back to Alpaca as `since_id`
on reconnect. Null means stream-from-now (first-ever deploy, or after a
checkpoint loss).

"""
from alembic import op
import sqlalchemy as sa


revision = '12f4f0b0f5b2'
down_revision = '339563b12284'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sse_checkpoints',
        sa.Column('stream_name', sa.Text(), nullable=False),
        sa.Column('last_event_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('stream_name'),
    )


def downgrade() -> None:
    op.drop_table('sse_checkpoints')
