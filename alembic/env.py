import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings

# Ensure all models are imported so SQLModel picks up metadata
from app.models import (  # noqa: F401
    CartridgeStock,
    CartridgeStockMovement,
    CashRegister,
    EventLog,
    MediaAsset,
    MediaAssignment,
    MediaClientHeartbeat,
    MediaPlayer,
    MLFeatureSnapshot,
    MLModelRegistry,
    MLOfflineRiskPrediction,
    MLTonerPrediction,
    NetworkSwitch,
    Printer,
    User,
)

config = context.config

config.set_main_option("sqlalchemy.url", str(settings.ASYNC_DATABASE_URI))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
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
