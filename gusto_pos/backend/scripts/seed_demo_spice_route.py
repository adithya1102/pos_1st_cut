"""
Seed demo data: "Spice Route Kitchen" outlet + menu + one staff account.

PERSISTENT DEMO DATA (NOT TEST_CAREVO_ fixtures) — intended to stay so that
owner_app and customer_app can each reach real data end-to-end.

Safety:
  * Reads DATABASE_URL from backend/.env and PRINTS the ep-... host so the
    operator can confirm prod vs dev branch BEFORE anything is written
    (per AGENT_GUARDRAILS.md rule 1). Requires --confirm-prod to actually write.
  * Idempotent: re-running reuses existing rows (matched by name/username),
    inserts nothing twice.
  * ADDITIVE ONLY: pure INSERTs of new rows. No UPDATE/DELETE of existing data,
    no DDL. Does not touch any other outlet/org/user.

Usage:
    cd gusto_pos/backend
    python scripts/seed_demo_spice_route.py            # dry run: prints plan + host, writes nothing
    python scripts/seed_demo_spice_route.py --confirm-prod   # actually writes
"""
import os
import sys
import uuid
from pathlib import Path

import psycopg2
from passlib.context import CryptContext

# Mirrors app.core.security.pwd_context exactly, so verify_password() accepts
# the hash we write and /api/v1/auth/login succeeds for the seeded staff user.
pwd_context = CryptContext(schemes=["sha256_crypt", "md5_crypt"], deprecated="auto")

# ---- demo data definition -------------------------------------------------
ORG_NAME = "Spice Route Foods"
OUTLET_NAME = "Spice Route Kitchen"
OUTLET_CITY = "Bengaluru"
OUTLET_LAT, OUTLET_LNG = 12.9716, 77.5946

STAFF_USERNAME = "spice_owner"
STAFF_PASSWORD = "Spice@123"          # printed at the end for the operator

# (category, name, base_price, is_veg, prep_time_minutes)
MENU = [
    ("Starters",  "Paneer Tikka",        220.0, True,  15),
    ("Starters",  "Chicken 65",          260.0, False, 18),
    ("Mains",     "Veg Biryani",         240.0, True,  20),
    ("Mains",     "Butter Chicken",      320.0, False, 22),
    ("Mains",     "Dal Makhani",         210.0, True,  18),
    ("Beverages", "Masala Chai",          40.0, True,   5),
]


def read_database_url() -> str:
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines():
        if line.strip().startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found in backend/.env")


def to_psycopg2(url: str) -> str:
    # psycopg2 wants a plain libpq URL, not the asyncpg dialect.
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("?ssl=require", "?sslmode=require")


def host_of(url: str) -> str:
    return url.split("@", 1)[1].split("/", 1)[0] if "@" in url else "?"


def main() -> None:
    raw = read_database_url()
    host = host_of(raw)
    confirm = "--confirm-prod" in sys.argv

    print("=" * 70)
    print(f"Target DB host : {host}")
    print(f"  -> This is {'PROD (ep-morning-meadow-...)' if 'ep-morning-meadow' in host else 'a DIFFERENT branch — VERIFY before writing'}")
    print(f"Mode           : {'WRITE (--confirm-prod)' if confirm else 'DRY RUN (no writes)'}")
    print("=" * 70)
    print("\nPlan (idempotent - existing rows are reused, not duplicated):")
    print(f"  organization : {ORG_NAME!r}")
    print(f"  outlet       : {OUTLET_NAME!r}  ({OUTLET_CITY}, {OUTLET_LAT},{OUTLET_LNG}, is_visible=true)")
    print(f"  menu         : 1 latest menu, categories {sorted(set(c for c,*_ in MENU))}")
    for cat, name, price, veg, prep in MENU:
        print(f"    - [{cat}] {name}  Rs.{price}  {'veg' if veg else 'non-veg'}  prep {prep}min  is_available=true")
    print(f"  staff user   : username={STAFF_USERNAME!r}  password={STAFF_PASSWORD!r}  (scoped to outlet)")

    if not confirm:
        print("\nDRY RUN — nothing written. Re-run with --confirm-prod to apply.")
        return

    conn = psycopg2.connect(to_psycopg2(raw))
    conn.autocommit = False
    cur = conn.cursor()
    try:
        # ---- organization (reuse if present) -----------------------------
        cur.execute("SELECT id FROM organizations WHERE name = %s", (ORG_NAME,))
        row = cur.fetchone()
        if row:
            org_id = row[0]; print(f"  SKIP org (exists) {org_id}")
        else:
            org_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO organizations (id, name, created_at) VALUES (%s, %s, now())",
                (org_id, ORG_NAME),
            )
            print(f"  ADD org {org_id}")

        # ---- outlet (reuse if present) -----------------------------------
        cur.execute("SELECT id FROM outlets WHERE location_name = %s", (OUTLET_NAME,))
        row = cur.fetchone()
        if row:
            outlet_id = row[0]; print(f"  SKIP outlet (exists) {outlet_id}")
        else:
            outlet_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO outlets
                   (id, location_name, city, latitude, longitude,
                    geofence_radius_meters, organization_id, is_visible, created_at)
                   VALUES (%s,%s,%s,%s,%s,100,%s,true, now())""",
                (outlet_id, OUTLET_NAME, OUTLET_CITY, OUTLET_LAT, OUTLET_LNG, org_id),
            )
            print(f"  ADD outlet {outlet_id}")

        # ---- menu (reuse latest if present) ------------------------------
        cur.execute(
            "SELECT id FROM menus WHERE outlet_id = %s AND is_latest = true", (outlet_id,)
        )
        row = cur.fetchone()
        if row:
            menu_id = row[0]; print(f"  SKIP menu (exists) {menu_id}")
        else:
            menu_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) "
                "VALUES (%s,%s,%s,true, now())",
                (menu_id, outlet_id, "v1"),
            )
            print(f"  ADD menu {menu_id}")

        # ---- categories + items ------------------------------------------
        cat_ids: dict[str, str] = {}
        for cat_name in dict.fromkeys(c for c, *_ in MENU):  # preserve order, unique
            cur.execute(
                "SELECT id FROM categories WHERE menu_id = %s AND name = %s",
                (menu_id, cat_name),
            )
            row = cur.fetchone()
            if row:
                cat_ids[cat_name] = row[0]; print(f"  SKIP category {cat_name} ({row[0]})")
            else:
                cid = str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO categories (id, menu_id, name, created_at) VALUES (%s,%s,%s, now())",
                    (cid, menu_id, cat_name),
                )
                cat_ids[cat_name] = cid; print(f"  ADD category {cat_name} ({cid})")

        for cat, name, price, veg, prep in MENU:
            cur.execute(
                "SELECT id FROM menu_items WHERE category_id = %s AND name = %s",
                (cat_ids[cat], name),
            )
            if cur.fetchone():
                print(f"  SKIP item {name} (exists)"); continue
            iid = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO menu_items
                   (id, category_id, name, base_price, is_veg, is_active,
                    is_available, prep_time_minutes, created_at)
                   VALUES (%s,%s,%s,%s,%s,true,true,%s, now())""",
                (iid, cat_ids[cat], name, price, veg, prep),
            )
            print(f"  ADD item {name} ({iid})")

        # ---- staff user (reuse if present) -------------------------------
        cur.execute("SELECT id FROM users WHERE username = %s", (STAFF_USERNAME,))
        row = cur.fetchone()
        if row:
            print(f"  SKIP user (exists) {row[0]}")
        else:
            uid = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO users
                   (id, username, hashed_password, is_active, outlet_id, created_at)
                   VALUES (%s,%s,%s,true,%s, now())""",
                (uid, STAFF_USERNAME, pwd_context.hash(STAFF_PASSWORD), outlet_id),
            )
            print(f"  ADD user {uid}")

        conn.commit()
        print("\n[OK] Demo seed committed.")
        print(f"  outlet_id = {outlet_id}")
        print(f"  owner_app login -> username={STAFF_USERNAME}  password={STAFF_PASSWORD}")
    except Exception:
        conn.rollback()
        print("\n[ROLLBACK] Seed failed — no rows written.")
        raise
    finally:
        cur.close(); conn.close()


if __name__ == "__main__":
    main()
