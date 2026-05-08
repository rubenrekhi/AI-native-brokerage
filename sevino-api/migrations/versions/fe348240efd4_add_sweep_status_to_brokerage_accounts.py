"""add sweep status to brokerage accounts

Tracks per-account FDIC cash-sweep enrollment lifecycle returned by Alpaca's
APR-tier API (PATCH /v1/accounts/{id}). sweep_status holds the lifecycle
string from Alpaca; sweep_enrolled_at is set when the account first enters
the enrolled state. Both columns are nullable so existing rows tolerate the
schema change before any code reads/writes them.

Revision ID: fe348240efd4
Revises: 5e7569489093
Create Date: 2026-05-06 18:29:05.278832

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fe348240efd4'
down_revision = '5e7569489093'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'brokerage_accounts',
        sa.Column('sweep_status', sa.Text(), nullable=True),
    )
    op.add_column(
        'brokerage_accounts',
        sa.Column('sweep_enrolled_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('brokerage_accounts', 'sweep_enrolled_at')
    op.drop_column('brokerage_accounts', 'sweep_status')
