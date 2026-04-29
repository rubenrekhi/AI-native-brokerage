"""add phone_verified_at to user_profiles

Revision ID: 866087a87e2d
Revises: a7c1d9e2f4b8
Create Date: 2026-04-24 00:39:57.916732

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '866087a87e2d'
down_revision = 'a7c1d9e2f4b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_profiles', 'phone_verified_at')
