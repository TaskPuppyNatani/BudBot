"""Alembic environment for the asynchronous PostgreSQL engine."""

from asyncio import run
from logging.config import fileConfig

from alembic import context
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    inspect,
    pool,
)
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from budbot.core.config import get_settings
from budbot.database.base import Base
import budbot.models  # noqa: F401  # Register all model metadata for Alembic.

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option(
    "sqlalchemy.url", get_settings().database_url.replace("%", "%%")
)
target_metadata = Base.metadata
VERSION_NUM_LENGTH = 128


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        inspector = inspect(connection)
        if inspector.has_table("alembic_version"):
            version_column = next(
                column
                for column in inspector.get_columns("alembic_version")
                if column["name"] == "version_num"
            )
            current_length = version_column["type"].length
            if current_length is not None and current_length < VERSION_NUM_LENGTH:
                connection.exec_driver_sql(
                    "ALTER TABLE alembic_version "
                    f"ALTER COLUMN version_num TYPE VARCHAR({VERSION_NUM_LENGTH})"
                )
        else:
            version_table = Table(
                "alembic_version",
                MetaData(),
                Column("version_num", String(VERSION_NUM_LENGTH), nullable=False),
                PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
            )
            version_table.create(connection, checkfirst=True)
        # Inspector reads autobegin a transaction. Let Alembic own the migration
        # transaction after the safe, widening-only compatibility adjustment.
        if connection.in_transaction():
            connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
