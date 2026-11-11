"""Checksum-verified migration runner for the gusto_pos backend database.

Production today has migrations 001..033 already applied by hand, with no
tracking table. This tool lets that history be recorded once
(--baseline-through), then every later migration applied safely
(dry-run by default, --apply to execute).

The database URL is read ONLY from the MIGRATE_DATABASE_URL environment
variable — never from a CLI argument — and is never printed, in full or
masked, anywhere in this tool's output, including error messages.

Run from gusto_pos/backend:
  python scripts/apply_migrations.py                    # dry run (default)
  python scripts/apply_migrations.py --baseline-through 33
  python scripts/apply_migrations.py --apply

Exit codes: 0 success, 2 drift, 3 confirm-host mismatch, 4 failure.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent
DEFAULT_MIGRATIONS_DIR = BACKEND_DIR / "migrations"

TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _dsn_for_asyncpg(raw_url: str) -> str:
    # asyncpg's connect() does not understand SQLAlchemy's "+asyncpg" driver
    # suffix on the postgresql:// scheme.
    return raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _host_of(raw_url: str) -> str:
    return urlsplit(_dsn_for_asyncpg(raw_url)).hostname or ""


def _get_database_url() -> str:
    url = os.environ.get("MIGRATE_DATABASE_URL")
    if not url:
        raise SystemExit(
            "MIGRATE_DATABASE_URL is not set. This tool reads the database "
            "URL only from that environment variable and accepts no "
            "equivalent command-line argument."
        )
    return url


def discover_migrations(migrations_dir: Path):
    """Return [(version, path, sha256_checksum), ...] in numeric order."""
    files = sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
    result = []
    for f in files:
        version = f.name.split("_", 1)[0]
        checksum = hashlib.sha256(f.read_bytes()).hexdigest()
        result.append((version, f, checksum))
    return result


async def _tracking_table_exists(conn) -> bool:
    return bool(await conn.fetchval(
        "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
    ))


async def _fetch_tracking_rows(conn) -> dict:
    if not await _tracking_table_exists(conn):
        return {}
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


async def _ensure_tracking_table(conn) -> None:
    await conn.execute(TRACKING_TABLE_SQL)


async def cmd_dry_run(conn, migrations) -> int:
    applied = await _fetch_tracking_rows(conn)
    drift = False
    for version, path, checksum in migrations:
        if version in applied:
            if applied[version] != checksum:
                print(f"DRIFT {version} {path.name}")
                drift = True
            else:
                print(f"ALREADY_APPLIED {version} {path.name}")
        else:
            print(f"PENDING {version} {path.name}")
    return 2 if drift else 0


async def cmd_baseline_through(conn, migrations, n: int) -> int:
    await _ensure_tracking_table(conn)
    row_count = await conn.fetchval("SELECT count(*) FROM schema_migrations")
    if row_count:
        print(
            "REFUSED: schema_migrations already has rows; "
            "--baseline-through is only for an empty tracking table."
        )
        return 4
    through = [(v, p, c) for v, p, c in migrations if int(v) <= n]
    if not through:
        print(f"REFUSED: no migration files with version <= {n:03d} found.")
        return 4
    applied = await _fetch_tracking_rows(conn)
    already = [v for v, _, _ in through if v in applied]
    if already:
        print(f"REFUSED: versions already recorded: {', '.join(already)}")
        return 4
    async with conn.transaction():
        for version, _path, checksum in through:
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum) "
                "VALUES ($1, $2)",
                version, checksum,
            )
    for version, path, _checksum in through:
        print(f"BASELINED {version} {path.name}")
    return 0


async def cmd_apply(conn, migrations) -> int:
    await _ensure_tracking_table(conn)
    applied = await _fetch_tracking_rows(conn)
    pending = []
    for version, path, checksum in migrations:
        if version in applied:
            if applied[version] != checksum:
                print(f"DRIFT {version} {path.name}")
                return 2
            continue
        pending.append((version, path, checksum))
    if not pending:
        print("Nothing pending.")
        return 0
    for version, path, checksum in pending:
        sql = path.read_text(encoding="utf-8")
        try:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) "
                    "VALUES ($1, $2)",
                    version, checksum,
                )
        except Exception as exc:
            print(f"FAILED {version} {path.name}: {exc.__class__.__name__}")
            return 4
        print(f"APPLIED {version} {path.name}")
    return 0


async def run(args) -> int:
    raw_url = _get_database_url()
    migrations_dir = (
        Path(args.migrations_dir) if args.migrations_dir
        else DEFAULT_MIGRATIONS_DIR
    )
    migrations = discover_migrations(migrations_dir)
    if not migrations:
        print(f"No migration files found in {migrations_dir}")
        return 4

    if args.apply:
        confirm = os.environ.get("MIGRATE_CONFIRM_HOST")
        host = _host_of(raw_url)
        if not confirm or confirm != host:
            print(
                "REFUSED: MIGRATE_CONFIRM_HOST is not set or does not match "
                "the target database host. Nothing was applied."
            )
            return 3

    dsn = _dsn_for_asyncpg(raw_url)
    try:
        conn = await asyncpg.connect(dsn=dsn)
    except Exception:
        print("ERROR: could not connect to the target database.")
        return 4

    try:
        if args.baseline_through is not None:
            return await cmd_baseline_through(
                conn, migrations, args.baseline_through)
        if args.apply:
            return await cmd_apply(conn, migrations)
        return await cmd_dry_run(conn, migrations)
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or apply gusto_pos backend migrations against the "
            "database named by MIGRATE_DATABASE_URL. Default mode is a "
            "dry run that changes nothing."
        )
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Execute all PENDING migrations, each in its own transaction.")
    parser.add_argument(
        "--baseline-through", type=int, default=None, metavar="N",
        help=(
            "Record versions 001..N as already applied, without executing "
            "them. Refuses if schema_migrations already has rows."
        ))
    parser.add_argument(
        "--migrations-dir", default=None,
        help="Override the migrations directory. For testing only.")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
