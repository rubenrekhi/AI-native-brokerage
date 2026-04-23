"""add assets table

Revision ID: a7c1d9e2f4b8
Revises: 12f4f0b0f5b2
Create Date: 2026-04-23 18:00:00.000000

Creates the `assets` table backing stock search. Enables the `pg_trgm`
extension and adds trigram GIN indexes on `symbol` and `name` so prefix
and substring ILIKE queries stay fast as the catalog grows. A partial
index on `tradeable = TRUE` keeps search scans over the tradeable subset
tight (untradeable rows still exist for historical reference but aren't
queried in the hot path).

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c1d9e2f4b8'
down_revision = '12f4f0b0f5b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.create_table(
        'assets',
        sa.Column('symbol', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('exchange', sa.Text(), nullable=True),
        sa.Column(
            'tradeable', sa.Boolean(), server_default='true', nullable=False
        ),
        sa.Column('logo_url', sa.Text(), nullable=True),
        sa.Column('alpaca_asset_id', sa.Text(), nullable=True),
        sa.Column(
            'synced_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('symbol'),
        sa.UniqueConstraint('alpaca_asset_id'),
    )

    op.execute(
        "CREATE INDEX ix_assets_symbol_trgm "
        "ON assets USING gin (symbol gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX ix_assets_name_trgm "
        "ON assets USING gin (name gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX ix_assets_tradeable "
        "ON assets (symbol) WHERE tradeable = TRUE;"
    )

    op.execute("""
        CREATE TRIGGER trg_assets_updated_at
        BEFORE UPDATE ON assets
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_assets_updated_at ON assets;")
    op.execute("DROP INDEX IF EXISTS ix_assets_tradeable;")
    op.execute("DROP INDEX IF EXISTS ix_assets_name_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_assets_symbol_trgm;")
    op.drop_table('assets')
    # pg_trgm left installed; other features may depend on it.
