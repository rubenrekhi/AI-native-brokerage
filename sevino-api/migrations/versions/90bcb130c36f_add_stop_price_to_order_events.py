"""add stop_price to order_events

Revision ID: 90bcb130c36f
Revises: b2d9f4c1a3e7
Create Date: 2026-06-01 19:35:12.212520

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '90bcb130c36f'
down_revision = 'b2d9f4c1a3e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'order_events',
        sa.Column('stop_price', sa.Numeric(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('order_events', 'stop_price')
