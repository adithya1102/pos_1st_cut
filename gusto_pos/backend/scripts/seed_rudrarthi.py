"""
Seed the complete Rudrarthi restaurant menu into the database.
Safe to run multiple times — checks existing data before inserting.
"""
import asyncio
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal

MENU_ID = "dc88b6a6-129c-479f-8609-07b8525f4310"

# ============================================================
# COMPLETE RUDRARTHI MENU
# Format: (name, base_price, is_veg, short_code)
#
# NOTE: short_code has UNIQUE constraint in DB.
# Duplicate codes from original spec have been fixed:
#   Palak Paneer: PP -> PLKP  (PP used by Pani Puri)
#   Kadai Chicken: KC -> KDC  (KC used by Kaju Curry)
#   Chicken Bhuna: CB -> CHB  (CB used by Corn Bhel)
#   Mutton Masala: MM -> MTM  (MM used by Mushroom Masala)
# ============================================================

MENU_DATA = {
    "Soups & Shorbas": [
        ("Cream of Tomato", 140, True, "COT"),
        ("Sweet Corn Soup Veg", 150, True, "SCSV"),
        ("Sweet Corn Soup Non-Veg", 170, False, "SCSNV"),
        ("Manchow Soup Veg", 160, True, "MSV"),
        ("Manchow Soup Non-Veg", 180, False, "MSNV"),
        ("Hot & Sour Soup Veg", 160, True, "HSSV"),
        ("Hot & Sour Soup Non-Veg", 180, False, "HSSNV"),
        ("Lemon Coriander Soup Veg", 150, True, "LCSV"),
        ("Lemon Coriander Soup Non-Veg", 170, False, "LCSNV"),
        ("Clear Vegetable Soup", 140, True, "CVS"),
        ("Clear Chicken Soup", 160, False, "CCS"),
        ("Tamatar Dhaniya Shorba", 130, True, "TDS"),
        ("Murgh Shorba", 190, False, "MS"),
        ("Lung Fung Soup Veg", 170, True, "LFSV"),
        ("Lung Fung Soup Non-Veg", 190, False, "LFSNV"),
        ("Cream of Mushroom", 160, True, "COM"),
    ],

    "Chaats & Quick Bites": [
        ("Pani Puri", 80, True, "PP"),
        ("Dahi Puri", 120, True, "DP"),
        ("Sev Puri", 110, True, "SP"),
        ("Papdi Chaat", 120, True, "PC"),
        ("Bhel Puri", 90, True, "BP"),
        ("Aloo Tikki Chaat", 110, True, "ATC"),
        ("Raj Kachori", 150, True, "RK"),
        ("Samosa Chaat", 100, True, "SC"),
        ("Corn Bhel", 130, True, "CB"),
        ("Peanut Masala", 140, True, "PM"),
    ],

    "Starters - Vegetarian": [
        ("Paneer Tikka Classic", 280, True, "PTC"),
        ("Paneer Malai Tikka", 310, True, "PMT"),
        ("Paneer 65", 280, True, "P65"),
        ("Hara Bhara Kebab", 240, True, "HBK"),
        ("Veg Seekh Kebab", 250, True, "VSK"),
        ("Gobi Manchurian Dry", 190, True, "GMD"),
        ("Chilli Paneer Dry", 270, True, "CPD"),
        ("Dahi Ke Sholay", 260, True, "DKS"),
        ("Crispy Honey Chilli Potato", 220, True, "CHCP"),
        ("Veg Manchurian Dry", 210, True, "VMD"),
        ("Mushroom Duplex", 260, True, "MD"),
        ("Chilli Mushroom", 240, True, "CM"),
        ("Crispy Corn Salt & Pepper", 220, True, "CCSP"),
        ("Baby Corn Manchurian", 220, True, "BCM"),
        ("Cheese Cherry Pineapple", 180, True, "CCP"),
    ],

    "Starters - Non-Vegetarian": [
        ("Chicken Tikka", 340, False, "CT"),
        ("Murgh Malai Tikka", 360, False, "MMT"),
        ("Tandoori Chicken Half", 380, False, "TCH"),
        ("Tandoori Chicken Full", 680, False, "TCF"),
        ("Chicken Lollipop", 320, False, "CL"),
        ("Lemon Chicken", 340, False, "LC"),
        ("Chicken Garlic Tikka", 350, False, "CGT"),
        ("Afgani Chicken", 370, False, "AC"),
        ("Chicken Seekh Kebab", 320, False, "CSK"),
        ("Tangdi Kebab", 350, False, "TK"),
        ("Chilli Chicken Dry", 310, False, "CCD"),
        ("Chicken 65", 300, False, "C65"),
        ("Dragon Chicken", 330, False, "DC"),
        ("Fish Amritsari", 390, False, "FA"),
        ("Apollo Fish", 410, False, "AF"),
    ],

    "Main Course - Vegetarian": [
        ("Paneer Butter Masala", 310, True, "PBM"),
        ("Kadai Paneer", 310, True, "KP"),
        ("Palak Paneer", 290, True, "PLKP"),
        ("Paneer Lababdar", 320, True, "PL"),
        ("Matar Paneer", 280, True, "MP"),
        ("Malai Kofta", 330, True, "MK"),
        ("Mushroom Masala", 290, True, "MM"),
        ("Kaju Curry", 350, True, "KC"),
        ("Veg Jalfrezi", 260, True, "VJ"),
        ("Mix Veg Diwani Handi", 270, True, "MVDH"),
        ("Aloo Gobi Matar", 220, True, "AGM"),
        ("Baingan Bharta", 240, True, "BB"),
        ("Dal Makhani", 250, True, "DM"),
        ("Dal Tadka Yellow", 190, True, "DTY"),
        ("Dal Fry", 180, True, "DF"),
    ],

    "Main Course - Non-Vegetarian": [
        ("Butter Chicken Boneless", 420, False, "BCB"),
        ("Kadai Chicken", 390, False, "KDC"),
        ("Chicken Curry Home Style", 360, False, "CCHS"),
        ("Chicken Bhuna", 380, False, "CHB"),
        ("Chicken Do Pyaza", 380, False, "CDP"),
        ("Chicken Rara", 440, False, "CR"),
        ("Mutton Rogan Josh", 480, False, "MRJ"),
        ("Mutton Masala", 490, False, "MTM"),
        ("Fish Curry", 420, False, "FC"),
        ("Egg Curry", 220, False, "EC"),
    ],

    "Breads & Rice": [
        ("Tandoori Roti Butter", 40, True, "TRB"),
        ("Plain Naan", 50, True, "PN"),
        ("Butter Naan", 70, True, "BN"),
        ("Garlic Naan", 90, True, "GN"),
        ("Laccha Paratha", 70, True, "LP"),
        ("Stuffed Kulcha", 110, True, "SK"),
        ("Veg Dum Biryani", 280, True, "VDB"),
        ("Chicken Dum Biryani", 350, False, "CDB"),
        ("Mutton Biryani", 450, False, "MB"),
        ("Jeera Rice", 180, True, "JR"),
        ("Steamed Basmati Rice", 150, True, "SBR"),
    ],

    "Indo-Chinese Main": [
        ("Veg Fried Rice", 210, True, "VFR"),
        ("Chicken Fried Rice", 250, False, "CFR"),
        ("Veg Schezwan Fried Rice", 230, True, "VSFR"),
        ("Chicken Schezwan Fried Rice", 270, False, "CSFR"),
        ("Veg Hakka Noodles", 210, True, "VHN"),
        ("Chicken Hakka Noodles", 250, False, "CHN"),
        ("Veg Chilli Garlic Noodles", 220, True, "VCGN"),
        ("Chicken Chilli Garlic Noodles", 260, False, "CCGN"),
        ("Veg American Chopsuey", 260, True, "VAC"),
        ("Chicken American Chopsuey", 310, False, "CAC"),
    ],

    "Juices & Shakes": [
        ("Fresh Lime Soda", 90, True, "FLS"),
        ("Fresh Lime Water", 90, True, "FLW"),
        ("Watermelon Juice", 120, True, "WJ"),
        ("Sweet Lassi", 110, True, "SL"),
        ("Salt Lassi", 110, True, "SaL"),
        ("Cold Coffee with Ice Cream", 160, True, "CCIC"),
        ("Chocolate Shake", 180, True, "CS"),
    ],

    "Desserts": [
        ("Gulab Jamun", 80, True, "GJ"),
        ("Rasmalai", 110, True, "RM"),
        ("Vanilla Ice Cream", 100, True, "VIC"),
        ("Sizzling Brownie", 220, True, "SB"),
        ("Tutti Frutti Sundae", 190, True, "TFS"),
    ],
}


async def get_or_create_category(db: AsyncSession, name: str, menu_id: str) -> str:
    """Get existing category or create new one."""
    result = await db.execute(
        text("SELECT id FROM menu_categories WHERE menu_id = :menu_id AND name = :name"),
        {"menu_id": menu_id, "name": name}
    )
    row = result.fetchone()
    if row:
        print(f"  Category EXISTS: {name}")
        return str(row[0])

    cat_id = str(uuid.uuid4())
    await db.execute(
        text("""INSERT INTO menu_categories (id, menu_id, name)
                VALUES (:id, :menu_id, :name)"""),
        {"id": cat_id, "menu_id": menu_id, "name": name}
    )
    print(f"  Category CREATED: {name}")
    return cat_id


async def get_or_create_item(
    db: AsyncSession,
    category_id: str,
    name: str,
    price: float,
    is_veg: bool,
    short_code: str,
) -> str:
    """Get existing item or create new one. Returns item id."""
    result = await db.execute(
        text("SELECT id FROM menu_items WHERE category_id = :cat_id AND name = :name"),
        {"cat_id": category_id, "name": name}
    )
    row = result.fetchone()
    if row:
        return str(row[0])

    item_id = str(uuid.uuid4())
    await db.execute(
        text("""INSERT INTO menu_items
                (id, category_id, name, short_code, base_price, is_veg, is_active)
                VALUES (:id, :cat_id, :name, :sc, :price, :is_veg, true)"""),
        {
            "id": item_id,
            "cat_id": category_id,
            "name": name,
            "sc": short_code,
            "price": price,
            "is_veg": is_veg,
        }
    )
    return item_id


async def seed():
    print("=" * 60)
    print("RUDRARTHI MENU SEEDING")
    print("=" * 60)

    total_categories = 0
    total_items = 0
    created_items = 0
    skipped_items = 0

    async with AsyncSessionLocal() as db:
        # First, check how many items exist already
        result = await db.execute(
            text("""SELECT COUNT(*) FROM menu_items mi
                    JOIN menu_categories mc ON mi.category_id = mc.id
                    WHERE mc.menu_id = :menu_id"""),
            {"menu_id": MENU_ID}
        )
        existing_count = result.scalar()
        print(f"\nExisting items in menu: {existing_count}")

        for category_name, items in MENU_DATA.items():
            print(f"\n[{category_name}]")
            cat_id = await get_or_create_category(db, category_name, MENU_ID)
            total_categories += 1

            for item_name, price, is_veg, short_code in items:
                # Check if already exists
                check = await db.execute(
                    text("SELECT id FROM menu_items WHERE category_id = :cat_id AND name = :name"),
                    {"cat_id": cat_id, "name": item_name}
                )
                exists = check.fetchone()

                if exists:
                    veg_label = "VEG" if is_veg else "NON-VEG"
                    print(f"    SKIP {veg_label:8} Rs.{price:4} -- {item_name}")
                    skipped_items += 1
                else:
                    await get_or_create_item(db, cat_id, item_name, price, is_veg, short_code)
                    veg_label = "VEG" if is_veg else "NON-VEG"
                    print(f"    ADD  {veg_label:8} Rs.{price:4} -- {item_name}")
                    created_items += 1
                total_items += 1

        await db.commit()

    # Verify final counts
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("""SELECT mc.name, COUNT(mi.id) as item_count
                    FROM menu_categories mc
                    LEFT JOIN menu_items mi ON mi.category_id = mc.id
                    WHERE mc.menu_id = :menu_id
                    GROUP BY mc.name
                    ORDER BY mc.name"""),
            {"menu_id": MENU_ID}
        )
        rows = result.fetchall()

        print("\n" + "=" * 60)
        print("SEEDING COMPLETE")
        print("=" * 60)
        print(f"Categories: {total_categories}")
        print(f"Total items processed: {total_items}")
        print(f"  Created: {created_items}")
        print(f"  Skipped (already existed): {skipped_items}")
        print(f"Menu ID: {MENU_ID}")
        print("\nFinal category counts:")
        total_in_db = 0
        for name, count in rows:
            print(f"  {name}: {count} items")
            total_in_db += count
        print(f"\nTotal items in database: {total_in_db}")
        print("=" * 60)
        print(f"\nVerify at: http://127.0.0.1:8000/api/v1/menus/{MENU_ID}")


if __name__ == "__main__":
    asyncio.run(seed())
