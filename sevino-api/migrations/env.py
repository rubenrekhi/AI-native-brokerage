import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.models import (  # noqa: F401, E402
    AchRelationship,
    Asset,
    Base,
    BrokerageAccount,
    Conversation,
    FeatureFlag,
    Message,
    OrderEvent,
    PlaidItem,
    RadarItem,
    SseCheckpoint,
    UserFinancialProfile,
    UserProfile,
    UserSettings,
)

target_metadata = Base.metadata


# Names of schema objects that live in the DB but intentionally aren't declared
# on any ORM model. Without this filter, `alembic revision --autogenerate`
# would generate a DROP for them every single run.
#
# `fk_user_profiles_auth_users` is the cross-schema FK from
# `user_profiles.id` → `auth.users.id`. It's created via raw SQL in the
# initial migration because `auth.users` is Supabase-managed and we
# deliberately keep it out of the SQLAlchemy models.
_AUTOGEN_IGNORED_NAMES: dict[str, set[str]] = {
    "foreign_key_constraint": {"fk_user_profiles_auth_users"},
}


def _include_object(object_, name, type_, reflected, compare_to):
    if name in _AUTOGEN_IGNORED_NAMES.get(type_, set()):
        return False
    return True


def _get_url() -> str:
    from app.config import settings
    return settings.database_url_direct


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL output)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using an async engine (required for asyncpg)."""
    from app.config import get_ssl_connect_args, settings

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=get_ssl_connect_args(settings.environment),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
