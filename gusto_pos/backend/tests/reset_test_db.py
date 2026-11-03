"""Safe local test-database reset tool.

Drops and recreates ONLY `carevo_test` on 127.0.0.1, then builds exactly the
schema tests/conftest.py expects, in the same two layers this codebase has
always built it in:

  1. The original ~21 "base" GustoPOS tables (organizations, outlets, tables,
     roles, users, customers, otp_validations, menus/menu_categories/
     menu_items/item_modifiers/menu_history, products, orders, order_items,
     payments, inventory, audit_logs, sync_logs, daily_sales_summary), via
     SQLAlchemy's Base.metadata.create_all() against the SAME models
     reset_db.py imports — preceded by one explicit
     `CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq`, because
     orders.readable_id's server_default names that sequence directly
     (app/modules/orders/model.py's own comment: "sequence created
     explicitly by reset_db.py") rather than via a SQLAlchemy Sequence
     object, so create_all() has no way to know to create it itself. These
     are the tables every later migration's foreign keys (customers(id),
     outlets(id), menu_items(id), ...) assume already exist —
     migrations/001_carevo_skip.sql's own header says so explicitly ("FKs to
     EXISTING customers(id) and outlets(id)").
  2. Every migrations/NNN_*.sql file, 001 through 038, applied in strict
     numeric order, each as one multi-statement execute() against the
     target database. This is what layers on every CareVo Skip / owner app /
     admin dashboard / loyalty-and-coupons / promotions / ... table and
     column the current test suite actually depends on — reset_db.py alone
     only produces the base tables and stops there, which is NOT what
     tests/conftest.py needs; this script is.

SAFETY, enforced BEFORE any network I/O:
  * Refuses to run unless the target host is exactly "127.0.0.1" or
    "localhost" AND the target database name is exactly "carevo_test".
  * Imports nothing that reads the real .env. The model modules imported for
    step 1 (app.modules.*.model) import only app.models.base — never
    app.core.config or app.core.database (which DOES import config.settings
    at module level, which is exactly what must not happen here). DATABASE
    credentials below are hardcoded local literals, never
    settings.DATABASE_URL.
  * Never touches any database other than carevo_test itself (the admin
    connection used to DROP/CREATE the database connects to the `postgres`
    maintenance database, as Postgres requires — it only ever runs
    DROP/CREATE DATABASE carevo_test and a connection-termination query
    filtered to datname = carevo_test).

Run from gusto_pos/backend:  python tests/reset_test_db.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine

HOST = "127.0.0.1"
PORT = 5432
DB_NAME = "carevo_test"
USER = "postgres"
PASSWORD = "postgres"
ADMIN_DB = "postgres"

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations"


def assert_safe_target(host: str, dbname: str) -> None:
    """The ONE safety gate. Pure string comparison, no I/O — callable
    standalone (see tests/test_reset_test_db_guard.py) to prove a hostile
    host or database name is refused before any connection is attempted.
    """
    if host not in ("127.0.0.1", "localhost"):
        raise SystemExit(
            f"REFUSED: host {host!r} is not 127.0.0.1 or localhost")
    if dbname != "carevo_test":
        raise SystemExit(
            f"REFUSED: database name {dbname!r} is not exactly carevo_test")


async def _drop_and_create_database() -> None:
    print(f"[1/4] Connecting to admin database '{ADMIN_DB}' on {HOST}:{PORT}...")
    conn = await asyncpg.connect(host=HOST, port=PORT, user=USER,
                                 password=PASSWORD, database=ADMIN_DB)
    try:
        print(f"[1/4] Terminating other connections to '{DB_NAME}'...")
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()", DB_NAME)
        print(f"[1/4] Dropping database '{DB_NAME}' if it exists...")
        await conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}"')
        print(f"[1/4] Creating database '{DB_NAME}'...")
        await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    finally:
        await conn.close()


async def _create_base_tables() -> int:
    print("[2/4] Creating base tables via SQLAlchemy models...")
    # Imported directly, never via app.core.database (which imports
    # app.core.config -> reads the real .env). Base is shared; importing
    # each model module registers its table on Base.metadata as a side
    # effect, exactly as reset_db.py's own import list does.
    from app.models.base import Base
    import app.modules.organizations.model  # noqa: F401
    import app.modules.outlets.model  # noqa: F401
    import app.modules.roles.model  # noqa: F401
    import app.modules.users.model  # noqa: F401
    import app.modules.customers.model  # noqa: F401
    import app.modules.otp.model  # noqa: F401
    import app.modules.menu.model  # noqa: F401
    import app.modules.products.model  # noqa: F401
    import app.modules.orders.model  # noqa: F401
    import app.modules.order_items.model  # noqa: F401
    import app.modules.payments.model  # noqa: F401
    import app.modules.inventory.model  # noqa: F401
    import app.modules.audit_logs.model  # noqa: F401
    import app.modules.sync_logs.model  # noqa: F401
    import app.modules.daily_sales.model  # noqa: F401

    url = f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            # orders.readable_id's server_default references this sequence
            # by name (app/modules/orders/model.py: "sequence created
            # explicitly by reset_db.py") rather than a SQLAlchemy Sequence
            # object, so create_all() does not know to create it — it must
            # exist before the orders table's CREATE TABLE runs.
            await conn.execute(sa_text(
                "CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq"))
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
    n = len(Base.metadata.tables)
    print(f"[2/4] Base tables created ({n} tables).")
    return n


async def _apply_migrations() -> int:
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise SystemExit(f"No migration files found in {MIGRATIONS_DIR}")
    print(f"[3/4] Applying {len(files)} migrations in numeric order...")
    conn = await asyncpg.connect(host=HOST, port=PORT, user=USER,
                                 password=PASSWORD, database=DB_NAME)
    try:
        for f in files:
            print(f"      -> {f.name}")
            sql = f.read_text(encoding="utf-8")
            await conn.execute(sql)
    finally:
        await conn.close()
    print(f"[3/4] All {len(files)} migrations applied.")
    return len(files)


async def _report_table_count() -> int:
    conn = await asyncpg.connect(host=HOST, port=PORT, user=USER,
                                 password=PASSWORD, database=DB_NAME)
    try:
        count = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'public'")
    finally:
        await conn.close()
    print(f"[4/4] Final table count: {count}")
    return count


async def main() -> None:
    assert_safe_target(HOST, DB_NAME)
    await _drop_and_create_database()
    await _create_base_tables()
    await _apply_migrations()
    await _report_table_count()


if __name__ == "__main__":
    asyncio.run(main())
