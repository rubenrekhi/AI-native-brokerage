"""add fractionable to assets

Caches Alpaca's per-asset `fractionable` flag so the trading service can
pre-reject fractional / notional orders against whole-shares-only symbols
without a round-trip. Defaults to TRUE so existing rows behave identically
to today's "forward and let Alpaca decide" path until the next sync run
populates real values.

Revision ID: 7a9c3e5b1d8f
Revises: 10f24d6dff33
Create Date: 2026-05-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a9c3e5b1d8f'
down_revision = '10f24d6dff33'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'assets',
        sa.Column(
            'fractionable',
            sa.Boolean(),
            server_default=sa.text('true'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('assets', 'fractionable')
