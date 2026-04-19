"""add unique plaid_item_id

Revision ID: 339563b12284
Revises: f4e5a18f3481
Create Date: 2026-04-18 21:45:49.496671

Adds a UNIQUE constraint on plaid_items.plaid_item_id to guarantee
link-bank idempotency at the DB level. Safe to apply instantly — the
plaid_items table is empty in every environment (bank linking ships in
a later PR).

"""
from alembic import op


revision = '339563b12284'
down_revision = 'f4e5a18f3481'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_plaid_items_plaid_item_id",
        "plaid_items",
        ["plaid_item_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_plaid_items_plaid_item_id",
        "plaid_items",
        type_="unique",
    )
