"""add updated at triggers to agent runtime tables

Revision ID: 5e7569489093
Revises: 9993b22329e1
Create Date: 2026-04-29 01:02:29.818918

The previous migration (9993b22329e1) created `agent_turns`,
`model_invocations`, and `tool_executions` but forgot to attach the
`BEFORE UPDATE` triggers that auto-set `updated_at = now()` — every
other table in the schema has these (see `b4900a105d3f` and
`a7c1d9e2f4b8`). Without them, raw-SQL writes (workers, manual ops)
leave `updated_at` stale.

`DROP TRIGGER IF EXISTS` first so this is safe to re-run on any
environment, including fresh ones that get the triggers from a future
consolidated migration.
"""
from alembic import op


revision = '5e7569489093'
down_revision = '9993b22329e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ['agent_turns', 'model_invocations', 'tool_executions']:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    for table in ['tool_executions', 'model_invocations', 'agent_turns']:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
