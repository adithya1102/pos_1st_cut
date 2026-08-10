"""Build a throwaway test database that mirrors prod's schema.

WHY THIS EXISTS
---------------
The API suite must not run against prod. An earlier session proved teardown
there is impossible: `order_events` carries an append-only trigger (migration
006) that rejects DELETE, and `order_events -> customer_orders -> customers`
are RESTRICT, so anything that writes an order leaves permanent rows behind.

A local throwaway database sidesteps that entirely — it gets dropped afterwards,
trigger and all.

The schema is built the same way prod's was: ORM metadata first, then every raw
migration in order. They are all idempotent (CREATE TABLE IF NOT EXISTS / ADD
COLUMN IF NOT EXISTS), so applying them over the ORM tables converges on the
same shape prod has.

Usage:
    python tests/bootstrap_test_db.py create
    python tests/bootstrap_test_db.py drop
"""
from __future__ import annotations

import asyncio
import os
import sys

import asyncpg

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

ADMIN_DSN = "postgresql://postgres:postgres@127.0.0.1:5432/postgres"
TEST_DB = "carevo_test"
TEST_DSN = f"postgresql://postgres:postgres@127.0.0.1:5432/{TEST_DB}"
TEST_URL = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/{TEST_DB}"

# Guard: never let this file touch anything that is not the local test DB.
assert "127.0.0.1" in TEST_DSN and TEST_DB.endswith("_test")


async def drop() -> None:
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute(
            f'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
            f"WHERE datname = '{TEST_DB}' AND pid <> pg_backend_pid()")
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        print(f"  dropped {TEST_DB}")
    finally:
        await conn.close()


async def create() -> None:
    await drop()
    conn = await asyncpg.connect(ADMIN_DSN)
    try:
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
        print(f"  created {TEST_DB}")
    finally:
        await conn.close()

    conn = await asyncpg.connect(TEST_DSN)
    try:
        # pgcrypto: migrations use gen_random_uuid().
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        # The legacy dine-in `orders` table defaults readable_id from this
        # sequence, so it must exist before create_all — same order reset_db.py
        # uses when building prod from scratch.
        await conn.execute("CREATE SEQUENCE IF NOT EXISTS orders_readable_id_seq")
    finally:
        await conn.close()

    # ORM tables. Point the app at the test DB BEFORE importing anything that
    # reads settings, or it will bind to prod.
    os.environ["DATABASE_URL"] = TEST_URL
    from sqlalchemy.ext.asyncio import create_async_engine     # noqa: E402
    import app.core.database as appdb                          # noqa: E402  (registers most models)
    from app.models.base import Base                           # noqa: E402
    import app.modules.carevo_customer.model                   # noqa: E402,F401
    import app.modules.audit_logs.model                        # noqa: E402,F401

    engine = create_async_engine(TEST_URL, echo=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print(f"  ORM metadata: {len(Base.metadata.tables)} tables")

    # Raw migrations, in order.
    mig_dir = os.path.join(BACKEND, "migrations")
    conn = await asyncpg.connect(TEST_DSN)
    applied, skipped = 0, []
    try:
        for name in sorted(os.listdir(mig_dir)):
            if not name.endswith(".sql"):
                continue
            sql = open(os.path.join(mig_dir, name), encoding="utf-8").read()
            try:
                await conn.execute(sql)
                applied += 1
            except Exception as exc:
                # Report rather than hide: a migration that cannot apply to a
                # fresh DB is worth knowing about even if the suite still runs.
                skipped.append((name, str(exc).split("\n")[0][:90]))
    finally:
        await conn.close()
    print(f"  migrations applied: {applied}")
    for n, e in skipped:
        print(f"    SKIPPED {n}: {e}")

    # SCHEMA DRIFT: prod has menu_items.tags, but no ORM model and no migration
    # creates it — it was added to prod by hand. /customer/menu SELECTs mi.tags,
    # so a database built purely from this repo cannot serve the menu endpoint.
    # Reproduced here so the test schema matches prod; the drift is reported
    # separately rather than silently papered over.
    conn = await asyncpg.connect(TEST_DSN)
    try:
        await conn.execute("ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS tags jsonb")
    finally:
        await conn.close()

    conn = await asyncpg.connect(TEST_DSN)
    try:
        n = await conn.fetchval(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        need = ["customers", "customer_orders", "order_events", "promotions",
                "promotion_redemptions", "push_notifications", "payment_transactions",
                "outlets", "users", "menu_items", "coupons", "point_transactions"]
        missing = [t for t in need if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=$1)", t)]
        print(f"  total tables: {n}")
        print(f"  required tables missing: {missing or 'NONE'}")
    finally:
        await conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(drop() if cmd == "drop" else create())
