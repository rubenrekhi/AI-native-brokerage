"""Integration test: the digest_snapshots migration applies and reverses
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
    "migrations.versions.e7f1a2b3c4d5_add_digest_snapshots_table"
)

EXPECTED_COLUMNS = {
    "id",
    "user_id",
    "ny_local_date",
    "cards",
    "generated_at",
    "dismissed_at",
    "created_at",
}


def _columns(sync_conn) -> set[str]:
    rows = sync_conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'digest_snapshots'"
        )
    ).fetchall()
    return {r[0] for r in rows}


def _table_present(sync_conn) -> bool:
    rows = sync_conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'digest_snapshots'"
        )
    ).fetchall()
    return len(rows) == 1


def _index_present(sync_conn) -> bool:
    rows = sync_conn.execute(
        text(
            "SELECT 1 FROM pg_indexes WHERE tablename = 'digest_snapshots' "
            "AND indexname = 'ix_digest_snapshots_user_date'"
        )
    ).fetchall()
    return len(rows) == 1


def _unique_constraint_present(sync_conn) -> bool:
    rows = sync_conn.execute(
        text(
            "SELECT 1 FROM pg_constraint "
            "WHERE conname = 'uq_digest_snapshots_user_date'"
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
            # DB starts at head — the table, index, and constraint exist.
            assert _table_present(sync_conn)
            assert _columns(sync_conn) == EXPECTED_COLUMNS
            assert _index_present(sync_conn)
            assert _unique_constraint_present(sync_conn)

            MIGRATION.downgrade()
            assert not _table_present(sync_conn)
            assert not _index_present(sync_conn)
            assert not _unique_constraint_present(sync_conn)

            MIGRATION.upgrade()
            assert _table_present(sync_conn)
            assert _columns(sync_conn) == EXPECTED_COLUMNS
            assert _index_present(sync_conn)
            assert _unique_constraint_present(sync_conn)
        finally:
            MIGRATION.op = original_op

    await conn.run_sync(_run)
