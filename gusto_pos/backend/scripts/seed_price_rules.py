"""
Seed price_rules for every menu_item that is missing 'normal' and/or 'ac' zone entries.

  normal price = item.base_price
  ac     price = round(item.base_price * 1.30, 2)

Idempotent — existing rows are left untouched.

Run from the backend/ folder:
    export PYTHONPATH=$(pwd)
    python scripts/seed_price_rules.py
"""
import asyncio
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func, text

from app.core.database import AsyncSessionLocal
from app.modules.menu.model import MenuItem, PriceRule

AC_MULTIPLIER = Decimal("1.30")


async def ensure_created_at(db) -> None:
    """Add created_at column to price_rules if the live DB is missing it."""
    r = await db.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'price_rules'
          AND column_name  = 'created_at'
    """))
    if not r.fetchone():
        await db.execute(text(
            "ALTER TABLE price_rules ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW()"
        ))
        await db.commit()
        print("  [DDL] price_rules.created_at column ADDED")


async def seed():
    async with AsyncSessionLocal() as db:
        await ensure_created_at(db)

        # Fetch all menu items
        items_result = await db.execute(select(MenuItem))
        items = items_result.scalars().all()

        # Build set of (str(menu_item_id), zone) that already exist
        existing_result = await db.execute(
            select(PriceRule.menu_item_id, PriceRule.zone)
        )
        existing: set[tuple[str, str]] = {
            (str(r.menu_item_id), r.zone) for r in existing_result.fetchall()
        }

        new_count = 0
        for item in items:
            item_id_str = str(item.id)
            base = Decimal(str(item.base_price))

            if (item_id_str, "normal") not in existing:
                db.add(PriceRule(
                    menu_item_id=item.id,
                    zone="normal",
                    price=float(base),
                    is_available=item.is_active,
                ))
                new_count += 1

            if (item_id_str, "ac") not in existing:
                ac_price = float(
                    (base * AC_MULTIPLIER).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
                db.add(PriceRule(
                    menu_item_id=item.id,
                    zone="ac",
                    price=ac_price,
                    is_available=item.is_active,
                ))
                new_count += 1

        await db.commit()

        # Count without selecting created_at (avoids schema-drift errors)
        total_row = await db.execute(select(func.count(PriceRule.id)))
        total = total_row.scalar_one()

        print(f"Items in DB      : {len(items)}")
        print(f"New rules added  : {new_count}")
        print(f"Total price_rules: {total}")


if __name__ == "__main__":
    asyncio.run(seed())
