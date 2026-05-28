#!/usr/bin/env python3
"""
add_kitchen_token.py
Adds the missing `kitchen_token` column to the orders table.

This is a one-time direct SQL fix. After running this script, create
a proper Alembic migration to track it:

    alembic revision --autogenerate -m "add kitchen_token to orders"
    alembic upgrade head

Usage:
    cd gusto_pos/backend
    python scripts/add_kitchen_token.py
"""

import os
import sys

# ── Inline the DB URL here or read from .env ──────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql://postgres:password@localhost:5432/gusto_pos"
    # Note: use psycopg2 (sync) here, NOT asyncpg
)


def main():
    try:
        import psycopg2
    except ImportError:
        print("✗ psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    print(f"Connecting to: {DATABASE_URL}")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    # Check if column already exists
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'orders' AND column_name = 'kitchen_token'
    """)
    exists = cur.fetchone()

    if exists:
        print("✓ kitchen_token column already exists — nothing to do.")
    else:
        print("Adding kitchen_token column to orders table...")
        cur.execute("ALTER TABLE orders ADD COLUMN kitchen_token VARCHAR(50);")
        print("✓ Column added successfully.")

    # Verify
    cur.execute("""
        SELECT column_name, data_type, character_maximum_length
        FROM information_schema.columns
        WHERE table_name = 'orders'
        ORDER BY ordinal_position
    """)
    print("\nCurrent orders table columns:")
    for row in cur.fetchall():
        print(f"  {row[0]:30s} {row[1]}" + (f"({row[2]})" if row[2] else ""))

    cur.close()
    conn.close()
    print("\n✅ Done. Now run: alembic revision --autogenerate -m 'add kitchen_token to orders'")


if __name__ == "__main__":
    main()
