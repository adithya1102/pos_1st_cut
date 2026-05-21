"""
seed_menu.py — Seed menu categories, items, and price_rules for the default outlet.

Idempotent: if the outlet already has an is_latest menu with items, exits early.
Otherwise creates a fresh menu, 3 categories, 6 items, and price_rules for both
normal and ac zones (ac = base_price * 1.30).

Run from the backend/ folder:
    $env:PYTHONPATH = (pwd).Path   # Windows PowerShell
    python seed_menu.py
"""
import asyncio
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.modules.outlets.model import Outlet
from app.modules.menu.model import Menu, MenuCategory, MenuItem

AC_MULTIPLIER = Decimal("1.30")

SEED_DATA = [
    {
        "name": "Starters",
        "items": [
            {"name": "Paneer Tikka",   "base_price": 220.00, "is_veg": True},
            {"name": "Chicken 65",     "base_price": 260.00, "is_veg": False},
        ],
    },
    {
        "name": "Biryani",
        "items": [
            {"name": "Chicken Biryani","base_price": 320.00, "is_veg": False},
            {"name": "Veg Biryani",    "base_price": 240.00, "is_veg": True},
            {"name": "Mutton Biryani", "base_price": 380.00, "is_veg": False},
        ],
    },
    {
        "name": "Drinks",
        "items": [
            {"name": "Coke",           "base_price":  60.00, "is_veg": True},
        ],
    },
]


async def ensure_price_rules_table(conn) -> None:
    """Create price_rules if it doesn't exist yet."""
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS price_rules (
            id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            menu_item_id UUID         NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
            zone         VARCHAR(20)  NOT NULL DEFAULT 'normal',
            price        NUMERIC(10,2) NOT NULL,
            is_available BOOLEAN      DEFAULT true,
            created_at   TIMESTAMPTZ  DEFAULT NOW(),
            UNIQUE(menu_item_id, zone)
        )
    """))


async def seed() -> None:
    async with AsyncSessionLocal() as db:

        # ── 0. Ensure price_rules table exists ────────────────────────────────
        await db.execute(text("""
            CREATE TABLE IF NOT EXISTS price_rules (
                id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
                menu_item_id UUID         NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
                zone         VARCHAR(20)  NOT NULL DEFAULT 'normal',
                price        NUMERIC(10,2) NOT NULL,
                is_available BOOLEAN      DEFAULT true,
                created_at   TIMESTAMPTZ  DEFAULT NOW(),
                UNIQUE(menu_item_id, zone)
            )
        """))
        await db.commit()

        # ── 1. Resolve the default outlet ────────────────────────────────────
        outlet_row = await db.execute(
            select(Outlet).order_by(Outlet.created_at).limit(1)
        )
        outlet = outlet_row.scalar_one_or_none()
        if not outlet:
            print("ERROR: No outlets in DB. Seed an outlet first.")
            return
        print(f"Outlet : {outlet.location_name}  ({outlet.id})")

        # ── 2. Guard: skip if the active menu already has items ───────────────
        existing = await db.execute(
            select(Menu).where(
                Menu.outlet_id == outlet.id,
                Menu.is_latest.is_(True),
            )
        )
        existing_menu = existing.scalar_one_or_none()
        if existing_menu:
            count_row = await db.execute(
                text(
                    "SELECT COUNT(*) FROM menu_items mi "
                    "JOIN categories c ON mi.category_id = c.id "
                    "WHERE c.menu_id = :mid"
                ),
                {"mid": str(existing_menu.id)},
            )
            if count_row.scalar() > 0:
                print("Menu already seeded. Nothing to do.")
                return

        # ── 3. Mark every existing menu for this outlet as not-latest ─────────
        await db.execute(
            text("UPDATE menus SET is_latest = false WHERE outlet_id = :oid"),
            {"oid": str(outlet.id)},
        )

        # ── 4. Create the new menu ────────────────────────────────────────────
        menu = Menu(outlet_id=outlet.id, version_label="v1", is_latest=True)
        db.add(menu)
        await db.flush()  # populate menu.id (FK for categories)
        print(f"Menu   : {menu.id}")

        # ── 5. Insert categories and items ───────────────────────────────────
        seeded_items: list[tuple[MenuItem, float]] = []

        for cat_data in SEED_DATA:
            cat = MenuCategory(menu_id=menu.id, name=cat_data["name"])
            db.add(cat)
            await db.flush()  # populate cat.id (FK for items)

            for item_data in cat_data["items"]:
                item = MenuItem(
                    category_id=cat.id,
                    name=item_data["name"],
                    base_price=item_data["base_price"],
                    is_veg=item_data["is_veg"],
                    is_active=True,
                )
                db.add(item)
                seeded_items.append((item, item_data["base_price"]))

            print(f"  [{cat_data['name']}] {len(cat_data['items'])} item(s)")

        await db.flush()  # populate item.id values before inserting price_rules

        # ── 6. Insert price_rules for normal and ac zones ─────────────────────
        rules_inserted = 0
        for item, base_price in seeded_items:
            base = Decimal(str(base_price))
            ac_price = float(
                (base * AC_MULTIPLIER).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            for zone, price in (("normal", float(base)), ("ac", ac_price)):
                await db.execute(
                    text(
                        "INSERT INTO price_rules (id, menu_item_id, zone, price, is_available) "
                        "VALUES (gen_random_uuid(), :mid, :zone, :price, true) "
                        "ON CONFLICT (menu_item_id, zone) DO NOTHING"
                    ),
                    {"mid": str(item.id), "zone": zone, "price": price},
                )
                rules_inserted += 1

        await db.commit()

        print(
            f"\nDone.  {len(seeded_items)} items  |  {rules_inserted} price_rules  "
            f"(normal + ac for each item)"
        )


if __name__ == "__main__":
    asyncio.run(seed())
