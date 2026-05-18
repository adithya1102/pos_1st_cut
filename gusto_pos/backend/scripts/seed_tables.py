"""
Seed physical Table records and active TableSession records for Rudrarthi.

Layout:  12 Normal tables (T-1 .. T-12) + 4 AC tables (A-1 .. A-4)
Outlet:  0b8a8349-6144-41a8-b028-b9089bd8eaea

Idempotent — safe to run multiple times.
  - Existing Table rows (matched on qr_token) are skipped.
  - Existing active unexpired sessions are reused, not duplicated.

After running, copy any printed /menu/{token} URL into your browser.

Run from the backend/ folder:
    export PYTHONPATH=$(pwd)
    python scripts/seed_tables.py
"""
import asyncio
import hashlib
import random
import string
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

OUTLET_ID = "0b8a8349-6144-41a8-b028-b9089bd8eaea"
SESSION_TTL_HOURS = 24

# (hash_index, table_number stored in DB, display_label, zone)
# hash_index is fed to generate_static_qr_token — must be unique across all tables.
# table_number is stored in the `tables.table_number` column (VARCHAR).
# validate_token builds session lookup key as f"T-{table_number}", so store pure ints.
TABLES = (
    [(i, str(i), f"T-{i}",    "normal") for i in range(1,  13)] +
    [(i, str(i), f"A-{i-12}", "ac")     for i in range(13, 17)]
)


def static_qr_token(outlet_id: str, table_index: int) -> str:
    """Deterministic 8-char token — matches generate_static_qr_token() in tables/router.py."""
    raw = f"{outlet_id}-table-{table_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8].upper()


def random_session_token(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


async def ensure_schema(db) -> tuple[str, str | None]:
    """
    Ensure qr_token column and table_sessions table exist.

    Returns (status_type, status_value) where:
      status_type  = 'integer' | 'enum' | None
      status_value = the correct literal to INSERT (e.g. '0', 'AVAILABLE', 'available', or None)
    """
    # 1. qr_token column on `tables` (may already exist)
    r = await db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'tables'
          AND column_name  = 'qr_token'
    """))
    if not r.fetchone():
        await db.execute(text("ALTER TABLE tables ADD COLUMN qr_token VARCHAR(12)"))
        print("  [DDL] tables.qr_token column ADDED")

    # 2. Unique index on qr_token (needed for ON CONFLICT; IF NOT EXISTS is safe)
    await db.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_tables_qr_token
        ON tables (qr_token)
    """))

    # 3. table_sessions table (IF NOT EXISTS — safe to re-run)
    await db.execute(text("""
        CREATE TABLE IF NOT EXISTS table_sessions (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            token       VARCHAR(8)  UNIQUE NOT NULL,
            outlet_id   UUID        NOT NULL,
            table_id    VARCHAR(20) NOT NULL,
            zone        VARCHAR(20) DEFAULT 'normal',
            is_active   BOOLEAN     DEFAULT true,
            created_at  TIMESTAMP   DEFAULT NOW(),
            expires_at  TIMESTAMP   NOT NULL,
            closed_at   TIMESTAMP
        )
    """))
    await db.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_table_sessions_token
        ON table_sessions (token)
    """))

    # 4. Detect `status` column type and its valid "available" literal.
    #    PostgreSQL may store the enum with uppercase member NAMES ('AVAILABLE')
    #    or lowercase VALUES ('available') depending on how SQLAlchemy created it.
    #    Query pg_enum to get the real first value rather than guessing.
    r = await db.execute(text("""
        SELECT c.data_type, c.udt_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name   = 'tables'
          AND c.column_name  = 'status'
    """))
    row = r.fetchone()
    if not row:
        return (None, None)       # status column absent — omit from INSERT

    data_type, udt_name = row
    if data_type == "integer":
        return ("integer", "0")

    # USER-DEFINED = PostgreSQL native enum type
    # Read the actual first enum label from the catalog
    r2 = await db.execute(text("""
        SELECT enumlabel FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = :udt
        ORDER BY e.enumsortorder
        LIMIT 1
    """), {"udt": udt_name})
    enum_row = r2.fetchone()
    available_label = enum_row[0] if enum_row else "available"
    return ("enum", available_label)


async def upsert_table(db, table_number: str, qr: str, status_type: str | None, status_value: str | None):
    """Insert a physical Table row, skipping if qr_token already exists.
    Always pass created_at explicitly — the Base model uses a Python-side default
    only, so PostgreSQL has no server DEFAULT for that column.
    """
    params = {"id": str(uuid.uuid4()), "oid": OUTLET_ID, "tnum": table_number, "qr": qr}
    if status_type == "integer":
        await db.execute(text("""
            INSERT INTO tables (id, outlet_id, table_number, qr_token, status, created_at)
            VALUES (:id, :oid, :tnum, :qr, 0, NOW())
            ON CONFLICT (qr_token) DO NOTHING
        """), params)
    elif status_type == "enum":
        # Use the catalog-verified label so casing is always correct
        await db.execute(text(f"""
            INSERT INTO tables (id, outlet_id, table_number, qr_token, status, created_at)
            VALUES (:id, :oid, :tnum, :qr, '{status_value}', NOW())
            ON CONFLICT (qr_token) DO NOTHING
        """), params)
    else:
        await db.execute(text("""
            INSERT INTO tables (id, outlet_id, table_number, qr_token, created_at)
            VALUES (:id, :oid, :tnum, :qr, NOW())
            ON CONFLICT (qr_token) DO NOTHING
        """), params)


async def get_or_create_session(db, table_id: str, zone: str, expires_at: datetime) -> tuple[str, bool]:
    """
    Return (token, is_new).
    Reuses an existing active unexpired session; creates one otherwise.

    `table_id` must match what validate_token constructs: f"T-{table_number}".
    """
    r = await db.execute(text("""
        SELECT token FROM table_sessions
        WHERE outlet_id = :oid
          AND table_id  = :tid
          AND is_active = true
          AND expires_at > NOW()
        LIMIT 1
    """), {"oid": OUTLET_ID, "tid": table_id})
    row = r.fetchone()
    if row:
        return row[0], False

    # Generate a globally unique 6-char token
    token = None
    for _ in range(30):
        candidate = random_session_token()
        chk = await db.execute(
            text("SELECT 1 FROM table_sessions WHERE token = :t"),
            {"t": candidate},
        )
        if not chk.fetchone():
            token = candidate
            break
    if token is None:
        token = random_session_token(8)  # fallback: 8-char to reduce collision chance

    await db.execute(text("""
        INSERT INTO table_sessions (id, token, outlet_id, table_id, zone, is_active, expires_at)
        VALUES (:id, :tok, :oid, :tid, :zone, true, :exp)
    """), {
        "id":   str(uuid.uuid4()),
        "tok":  token,
        "oid":  OUTLET_ID,
        "tid":  table_id,
        "zone": zone,
        "exp":  expires_at,
    })
    return token, True


async def seed():
    expires_at = datetime.utcnow() + timedelta(hours=SESSION_TTL_HOURS)

    async with AsyncSessionLocal() as db:
        print("=" * 72)
        print("RUDRARTHI TABLE + SESSION SEEDING")
        print("=" * 72)

        status_type, status_value = await ensure_schema(db)
        await db.commit()

        print(f"  [INFO] status column type={status_type}, insert value={status_value!r}")
        print(f"\n{'Label':<8} {'Zone':<8} {'Static QR (8-char)':<20} {'Session Token':<14} Menu URL")
        print("-" * 72)

        new_count = 0
        for hash_idx, table_number, label, zone in TABLES:
            qr = static_qr_token(OUTLET_ID, hash_idx)

            # Upsert physical table
            await upsert_table(db, table_number, qr, status_type, status_value)

            # Session lookup key must match validate_token's: f"T-{table_number}"
            table_id = f"T-{table_number}"

            session_token, is_new = await get_or_create_session(db, table_id, zone, expires_at)
            if is_new:
                new_count += 1

            tag = "NEW     " if is_new else "existing"
            print(f"{label:<8} {zone:<8} {qr:<20} {session_token:<14} /menu/{session_token}  [{tag}]")

        await db.commit()

    print()
    print(f"Sessions expire : {expires_at.strftime('%Y-%m-%d %H:%M')} UTC  ({SESSION_TTL_HOURS}h from now)")
    print(f"New sessions    : {new_count}")
    print()
    print("Copy any /menu/{token} URL above into the browser to test the menu.")
    print("For printed QR codes, use the 8-char Static QR value with /t/{qr_token}.")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(seed())
