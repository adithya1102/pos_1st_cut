"""Tests for scripts/apply_migrations.py, scenarios (a)-(g) from the go-live
migration-tool spec.

Runs ONLY against the local scratch database (127.0.0.1/carevo_test, same
one tests/reset_test_db.py manages) — never against any remote database.
Not named test_api_*.py on purpose: this suite's pytest.ini restricts
default collection to that pattern, so these do not get silently folded
into the main run's counts. Invoke explicitly:

  python -m pytest tests/test_migrations_tool.py -v

Each test is a plain sync function; async DB calls use their own
asyncio.run() so they never touch the session-scoped event loop
tests/conftest.py sets up for the (unrelated) main API test suite.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reset_test_db import (  # noqa: E402
    HOST, PORT, DB_NAME, USER, PASSWORD,
    assert_safe_target, _drop_and_create_database, _create_base_tables,
    MIGRATIONS_DIR,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BACKEND_DIR / "scripts" / "apply_migrations.py"

TEST_DB_URL = f"postgresql+asyncpg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"

# Collected across every test in this module; test_g_no_url_leak asserts
# none of it contains the scratch DB's connection string.
_ALL_CAPTURED_OUTPUT: list[str] = []


def _run_tool(*cli_args, confirm_host=None, env_url=TEST_DB_URL, migrations_dir=None):
    assert_safe_target(HOST, DB_NAME)  # same safety gate reset_test_db.py uses
    env = dict(os.environ)
    env["MIGRATE_DATABASE_URL"] = env_url
    env.pop("MIGRATE_CONFIRM_HOST", None)
    if confirm_host is not None:
        env["MIGRATE_CONFIRM_HOST"] = confirm_host
    args = [sys.executable, str(SCRIPT)]
    if migrations_dir is not None:
        args += ["--migrations-dir", str(migrations_dir)]
    args += list(cli_args)
    result = subprocess.run(
        args, cwd=str(BACKEND_DIR), env=env,
        capture_output=True, text=True, timeout=120,
    )
    _ALL_CAPTURED_OUTPUT.append(result.stdout)
    _ALL_CAPTURED_OUTPUT.append(result.stderr)
    return result


async def _connect():
    assert_safe_target(HOST, DB_NAME)
    return await asyncpg.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, database=DB_NAME)


async def _reset_base_only():
    assert_safe_target(HOST, DB_NAME)
    await _drop_and_create_database()
    await _create_base_tables()


async def _apply_subset_directly(max_version: int):
    """Physically apply migration files <= max_version, bypassing the tool
    under test — used to build a known pre-baseline production-like state."""
    assert_safe_target(HOST, DB_NAME)
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))
    files = [f for f in files if int(f.name.split("_", 1)[0]) <= max_version]
    conn = await asyncpg.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD, database=DB_NAME)
    try:
        for f in files:
            await conn.execute(f.read_text(encoding="utf-8"))
    finally:
        await conn.close()


async def _schema_migrations_rows():
    conn = await _connect()
    try:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        if not exists:
            return {}
        rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
        return {r["version"]: r["checksum"] for r in rows}
    finally:
        await conn.close()


def test_a_empty_db_dry_run_all_pending():
    asyncio.run(_reset_base_only())
    result = _run_tool()
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert lines, "expected per-file output lines"
    assert all(l.startswith("PENDING ") for l in lines), result.stdout


def test_b_apply_then_apply_again_is_noop():
    # continues from test_a's base-only DB
    result = _run_tool("--apply", confirm_host=HOST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAILED" not in result.stdout
    applied_lines = [l for l in result.stdout.splitlines() if l.startswith("APPLIED ")]
    assert len(applied_lines) == len(
        sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")))

    result2 = _run_tool("--apply", confirm_host=HOST)
    assert result2.returncode == 0, result2.stdout + result2.stderr
    assert "Nothing pending." in result2.stdout


def test_c_drift_reported(tmp_path):
    # DB still has every migration applied & recorded from test_b.
    real_001 = MIGRATIONS_DIR / "001_carevo_skip.sql"
    edited = tmp_path / "001_carevo_skip.sql"
    edited.write_text(real_001.read_text(encoding="utf-8") + "\n-- drift test\n",
                       encoding="utf-8")
    result = _run_tool(migrations_dir=tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "DRIFT 001" in result.stdout


def test_d_wrong_confirm_host_refuses_apply():
    result = _run_tool("--apply", confirm_host="not-the-real-host.example.com")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "REFUSED" in result.stdout


def test_e_baseline_through_33_then_apply_34_to_41():
    asyncio.run(_reset_base_only())
    asyncio.run(_apply_subset_directly(33))

    result = _run_tool("--baseline-through", "33", confirm_host=HOST)
    assert result.returncode == 0, result.stdout + result.stderr
    baselined = [l for l in result.stdout.splitlines() if l.startswith("BASELINED ")]
    assert len(baselined) == 33, result.stdout

    dry = _run_tool()
    assert dry.returncode == 0, dry.stdout + dry.stderr
    pending = [l for l in dry.stdout.splitlines() if l.startswith("PENDING ")]
    already = [l for l in dry.stdout.splitlines() if l.startswith("ALREADY_APPLIED ")]
    assert len(already) == 33, dry.stdout
    assert {l.split()[1] for l in pending} == {f"{n:03d}" for n in range(34, 42)}, dry.stdout

    apply_result = _run_tool("--apply", confirm_host=HOST)
    assert apply_result.returncode == 0, apply_result.stdout + apply_result.stderr
    applied = [l for l in apply_result.stdout.splitlines() if l.startswith("APPLIED ")]
    assert len(applied) == 8, apply_result.stdout


def test_f_failing_migration_stops_run(tmp_path):
    asyncio.run(_reset_base_only())
    (tmp_path / "001_ok.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "002_bad.sql").write_text("THIS IS NOT VALID SQL;", encoding="utf-8")

    result = _run_tool("--apply", confirm_host=HOST, migrations_dir=tmp_path)
    assert result.returncode == 4, result.stdout + result.stderr
    assert "APPLIED 001" in result.stdout
    assert "FAILED 002" in result.stdout

    rows = asyncio.run(_schema_migrations_rows())
    assert "001" in rows
    assert "002" not in rows


def test_g_no_connection_string_leaked():
    assert _ALL_CAPTURED_OUTPUT, "no output captured — tests a-f did not run first"
    needle = f"{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"
    for chunk in _ALL_CAPTURED_OUTPUT:
        assert needle not in chunk
        assert TEST_DB_URL not in chunk
