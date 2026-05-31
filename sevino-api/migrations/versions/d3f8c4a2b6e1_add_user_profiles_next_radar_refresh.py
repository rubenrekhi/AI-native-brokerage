"""add user_profiles.next_radar_refresh_at

Stores the per-user anchor timestamp for the AI Radar batch cadence
(product spec §13.6). NULL until the first batch is generated. The
orchestrator advances this column by 7 days from the prior value on every
successful batch — additive, nullable, no backfill required.

Revision ID: d3f8c4a2b6e1
Revises: b7e3c1a9f2d4
Create Date: 2026-05-30 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd3f8c4a2b6e1'
down_revision = 'b7e3c1a9f2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column(
            'next_radar_refresh_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('user_profiles', 'next_radar_refresh_at')
