#!/usr/bin/env python3
"""
bootstrap_migrations.py
Run this ONCE on your existing database to:
  1. Tell Alembic "the current DB is at the baseline revision"
  2. Apply any pending migrations after baseline

Usage:
    cd gusto_pos/backend
    python scripts/bootstrap_migrations.py
"""

import subprocess
import sys


def run(cmd: list[str]) -> None:
    print(f"\n▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"✗ Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    print("✓ Done")


if __name__ == "__main__":
    # Step 1: stamp the existing DB as being at the baseline revision
    # This does NOT run any SQL — just inserts a row into alembic_version table
    run(["alembic", "stamp", "001_baseline"])

    # Step 2: show current status
    run(["alembic", "current"])

    # Step 3: apply any pending migrations after baseline
    run(["alembic", "upgrade", "head"])

    print("\n✅ Migration bootstrap complete.")
    print("   From now on, use: alembic revision --autogenerate -m 'your change'")
    print("   Then:             alembic upgrade head")
