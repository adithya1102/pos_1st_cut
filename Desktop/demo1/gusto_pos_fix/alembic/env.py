"""
Alembic env.py — async-compatible configuration for SQLAlchemy 2.0 + asyncpg.

How autogenerate works:
  1. It imports all models via `app.models` (which imports every ORM class).
  2. It compares Base.metadata (Python model definitions) against the live DB.
  3. It generates a migration script with ADD COLUMN / CREATE TABLE / DROP etc.

Run migrations:
  alembic revision --autogenerate -m "describe your change"
  alembic upgrade head
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Load all models so autogenerate can detect every table ────────────────────
from app.models import Base  # noqa: F401 — this import loads all ORM classes
import app.models.models  # noqa: F401 — explicit safety import

from app.core.config import settings

# ── Alembic config ────────────────────────────────────────────────────────────
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Offline migrations (no live DB connection) ────────────────────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,           # detect column type changes
        compare_server_default=True, # detect default value changes
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (live async DB connection) ──────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # no pooling during migrations
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
