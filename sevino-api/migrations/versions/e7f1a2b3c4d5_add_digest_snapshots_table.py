"""digest foundation: digest_snapshots table

Backs the Daily Digest — one LLM-curated card stack per user per NY-local
day, stored as a JSONB ``cards`` array. The ``(user_id, ny_local_date)``
unique constraint is the idempotency key both the morning cron and the
lazy-fallback read path upsert on, so neither can produce two rows for the
same day. ``ix_digest_snapshots_user_date`` (user_id, ny_local_date DESC)
serves the "latest digest for this user" lookup. ``dismissed_at`` records
the one-way dismissal flip. Rollback drops the table outright.

Revision ID: e7f1a2b3c4d5
Revises: d3f8c4a2b6e1
Create Date: 2026-05-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e7f1a2b3c4d5'
down_revision = 'd3f8c4a2b6e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'digest_snapshots',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('ny_local_date', sa.Date(), nullable=False),
        sa.Column(
            'cards',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False,
        ),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['user_profiles.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'ny_local_date', name='uq_digest_snapshots_user_date'
        ),
    )
    op.create_index(
        'ix_digest_snapshots_user_date',
        'digest_snapshots',
        ['user_id', sa.text('ny_local_date DESC')],
    )


def downgrade() -> None:
    op.drop_index('ix_digest_snapshots_user_date', table_name='digest_snapshots')
    op.drop_table('digest_snapshots')
