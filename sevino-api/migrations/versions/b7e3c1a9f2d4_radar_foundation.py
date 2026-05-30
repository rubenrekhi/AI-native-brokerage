"""radar foundation: asset enrichment + radar bucket

Adds the columns the AI Radar pipeline filters on. `assets` gains FMP
profile fields (sector/industry/market_cap/ipo_date/asset_type/country)
plus `enriched_at` so the daily sync can stagger enrichment. `enriched_at`
gets a btree index: the daily enrichment selector orders by it (NULLs
first) and the radar eligibility query filters on `IS NOT NULL`, both over
the full ~12k-row catalog. `radar_items` gains `bucket` so an AI pick
records which sourcing rule surfaced it (user-added rows leave it NULL).
All additive and nullable — rollback drops the index and columns.

Revision ID: b7e3c1a9f2d4
Revises: 7a9c3e5b1d8f
Create Date: 2026-05-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7e3c1a9f2d4'
down_revision = '7a9c3e5b1d8f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('assets', sa.Column('sector', sa.Text(), nullable=True))
    op.add_column('assets', sa.Column('industry', sa.Text(), nullable=True))
    op.add_column('assets', sa.Column('market_cap', sa.BigInteger(), nullable=True))
    op.add_column('assets', sa.Column('ipo_date', sa.Date(), nullable=True))
    op.add_column('assets', sa.Column('asset_type', sa.Text(), nullable=True))
    op.add_column('assets', sa.Column('country', sa.Text(), nullable=True))
    op.add_column(
        'assets',
        sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f('ix_assets_enriched_at'), 'assets', ['enriched_at']
    )
    op.add_column('radar_items', sa.Column('bucket', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('radar_items', 'bucket')
    op.drop_index(op.f('ix_assets_enriched_at'), table_name='assets')
    op.drop_column('assets', 'enriched_at')
    op.drop_column('assets', 'country')
    op.drop_column('assets', 'asset_type')
    op.drop_column('assets', 'ipo_date')
    op.drop_column('assets', 'market_cap')
    op.drop_column('assets', 'industry')
    op.drop_column('assets', 'sector')
