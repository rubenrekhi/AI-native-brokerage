"""add tax_id_last_4 to user_profiles

Revision ID: c8d2fa74e103
Revises: 866087a87e2d
Create Date: 2026-04-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8d2fa74e103'
down_revision = '866087a87e2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column('tax_id_last_4', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_profiles', 'tax_id_last_4')
