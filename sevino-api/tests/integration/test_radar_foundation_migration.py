"""Integration test: the radar_foundation migration applies and reverses
cleanly against real Postgres.

Runs the migration's own ``upgrade()`` / ``downgrade()`` inside the
rolling-back ``db_session`` transaction, so the DDL is exercised end-to-end
but never persists past the test.
"""

import importlib

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.conftest import _pg_available_sync

pytestmark = pytest.mark.skipif(
    not _pg_available_sync,
    reason="Local Supabase Postgres not available (run `make infra`)",
)

MIGRATION = importlib.import_module(
    "migrations.versions.b7e3c1a9f2d4_radar_foundation"
)

ASSET_COLUMNS = {
    "sector",
    "industry",
    "market_cap",
    "ipo_date",
    "asset_type",
    "country",
    "enriched_at",
}


def _asset_cols(sync_conn) -> set[str]:
    rows = sync_conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'assets'"
        )
    ).fetchall()
    return {r[0] for r in rows} & ASSET_COLUMNS


def _bucket_present(sync_conn) -> bool:
    rows = sync_conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'radar_items' AND column_name = 'bucket'"
        )
    ).fetchall()
    return len(rows) == 1


def _enriched_at_index_present(sync_conn) -> bool:
    rows = sync_conn.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename = 'assets' AND indexname = 'ix_assets_enriched_at'"
        )
    ).fetchall()
    return len(rows) == 1


async def test_migration_upgrade_downgrade_clean(db_session: AsyncSession):
    conn = await db_session.connection()

    def _run(sync_conn):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        ctx = MigrationContext.configure(connection=sync_conn)
        operations = Operations(ctx)

        original_op = MIGRATION.op
        MIGRATION.op = operations
        try:
            # DB starts at head — the new columns and index are present.
            assert _asset_cols(sync_conn) == ASSET_COLUMNS
            assert _bucket_present(sync_conn)
            assert _enriched_at_index_present(sync_conn)

            MIGRATION.downgrade()
            assert _asset_cols(sync_conn) == set()
            assert not _bucket_present(sync_conn)
            assert not _enriched_at_index_present(sync_conn)

            MIGRATION.upgrade()
            assert _asset_cols(sync_conn) == ASSET_COLUMNS
            assert _bucket_present(sync_conn)
            assert _enriched_at_index_present(sync_conn)
        finally:
            MIGRATION.op = original_op

    await conn.run_sync(_run)
