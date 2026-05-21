import asyncio
import uuid
from decimal import Decimal
from sqlalchemy import select, String, ForeignKey, DECIMAL, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.base import Base
from app.modules.organizations.model import Organization
from app.modules.outlets.model import Outlet
from app.modules.menu.model import Menu, MenuCategory, MenuItem

# Define PriceRule locally since it's missing from the main models
class PriceRule(Base):
    __tablename__ = "price_rules"
    menu_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False)
    zone: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    price: Mapped[float] = mapped_column(DECIMAL(10, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)

OUTLET_ID = uuid.UUID("0b8a8349-6144-41a8-b028-b9089bd8eaea")

async def seed():
    async with AsyncSessionLocal() as db:
        # 1. Ensure Organization exists
        org_result = await db.execute(select(Organization).limit(1))
        org = org_result.scalar_one_or_none()
        if not org:
            org = Organization(name="Gusto POS Brand", gst_number="22AAAAA0000A1Z5")
            db.add(org)
            await db.flush()
            print(f"Created Organization: {org.name}")
        else:
            print(f"Using existing Organization: {org.name}")

        # 2. Ensure Outlet exists
        outlet_result = await db.execute(select(Outlet).where(Outlet.id == OUTLET_ID))
        outlet = outlet_result.scalar_one_or_none()
        if not outlet:
            outlet = Outlet(
                id=OUTLET_ID,
                organization_id=org.id,
                location_name="MAUI Demo Outlet",
                city="Bangalore"
            )
            db.add(outlet)
            await db.flush()
            print(f"Created Outlet: {outlet.location_name}")
        else:
            print(f"Using existing Outlet: {outlet.location_name}")

        # 3. Create Menu
        # Deactivate previous menus for this outlet
        await db.execute(
            Menu.__table__.update()
            .where(Menu.outlet_id == OUTLET_ID)
            .values(is_latest=False)
        )
        
        menu = Menu(
            outlet_id=OUTLET_ID,
            version_label="V1.0.0",
            is_latest=True
        )
        db.add(menu)
        await db.flush()
        print(f"Created Menu for outlet {OUTLET_ID}")

        # 4. Create Categories
        categories_data = ["Starters", "Biryani", "Drinks"]
        categories = []
        for cat_name in categories_data:
            cat = MenuCategory(menu_id=menu.id, name=cat_name)
            db.add(cat)
            categories.append(cat)
        
        await db.flush()
        print(f"Created {len(categories)} Categories")

        # 5. Create Items and Price Rules
        items_data = [
            # (Category Index, Name, Base Price, Is Veg)
            (0, "Paneer Tikka", 250.00, True),
            (0, "Chicken 65", 280.00, False),
            (1, "Veg Biryani", 220.00, True),
            (1, "Chicken Biryani", 320.00, False),
            (2, "Masala Chai", 40.00, True),
            (2, "Cold Coffee", 120.00, True),
        ]

        for cat_idx, name, price, is_veg in items_data:
            item = MenuItem(
                category_id=categories[cat_idx].id,
                name=name,
                base_price=price,
                is_veg=is_veg,
                is_active=True
            )
            db.add(item)
            await db.flush() # Get item.id
            
            # Price Rules
            # Normal zone
            db.add(PriceRule(
                menu_item_id=item.id,
                zone="normal",
                price=float(price),
                is_available=True
            ))
            # AC zone (30% markup)
            db.add(PriceRule(
                menu_item_id=item.id,
                zone="ac",
                price=float(round(price * 1.3, 2)),
                is_available=True
            ))
        
        await db.commit()
        print("Successfully seeded Menu, Categories, Items, and Price Rules!")

if __name__ == "__main__":
    asyncio.run(seed())
