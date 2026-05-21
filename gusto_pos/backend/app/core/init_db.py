"""Database seeding script — runs on every startup to ensure default data exists."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modules.roles.model import Role


async def init_initial_data(session: AsyncSession) -> None:
    result = await session.execute(select(Role))
    if result.scalars().first() is not None:
        return

    default_roles = [
        Role(name="Owner",   permissions={"all": True}),
        Role(name="Manager", permissions={"reports": True, "refunds": True, "manage_staff": True}),
        Role(name="Kitchen", permissions={"view_orders": True, "update_order_status": True}),
        Role(name="Waiter",  permissions={"create_orders": True, "manage_tables": True}),
    ]
    for role in default_roles:
        session.add(role)

    await session.commit()
    print("[OK] Default roles seeded: Owner, Manager, Kitchen, Waiter")
