"""Database seeding script for initial data setup."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modules.roles.model import Role
from app.modules.staff.model import Staff, StaffRole
from app.core.security import get_password_hash


async def init_initial_data(session: AsyncSession) -> None:
    """
    Initialize default roles and permissions if they don't exist.
    
    Args:
        session: AsyncSession for database operations
    """
    try:
        # Check if roles already exist
        result = await session.execute(select(Role))
        existing_roles = result.scalars().all()
        
        if len(existing_roles) > 0:
            print("[OK] Roles already exist in database. Skipping role seed.")
            await _seed_default_staff(session)
            return
        
        # Define default roles with their permissions
        default_roles = [
            {
                "name": "Owner",
                "permissions": {
                    "view_dashboard": True,
                    "manage_staff": True,
                    "manage_inventory": True,
                    "view_reports": True,
                    "manage_menus": True,
                    "manage_outlets": True,
                    "manage_organizations": True,
                    "manage_payments": True,
                    "view_audit_logs": True,
                }
            },
            {
                "name": "Manager",
                "permissions": {
                    "view_dashboard": True,
                    "manage_staff": True,
                    "manage_inventory": True,
                    "view_reports": True,
                    "manage_menus": True,
                    "manage_payments": True,
                    "view_audit_logs": False,
                }
            },
            {
                "name": "Kitchen",
                "permissions": {
                    "view_orders": True,
                    "update_order_status": True,
                    "view_kitchen_queue": True,
                    "print_kitchen_ticket": True,
                }
            },
            {
                "name": "Waiter",
                "permissions": {
                    "create_orders": True,
                    "view_orders": True,
                    "update_order_items": True,
                    "manage_tables": True,
                    "process_payments": True,
                    "view_menu": True,
                }
            },
        ]
        
        # Create and insert default roles
        for role_data in default_roles:
            role = Role(
                name=role_data["name"],
                permissions=role_data["permissions"]
            )
            session.add(role)
        
        await session.commit()
        print("[OK] Default roles created successfully!")
        print(f"  - Owner")
        print(f"  - Manager")
        print(f"  - Kitchen")
        print(f"  - Waiter")

        # Seed default staff after creating roles
        await _seed_default_staff(session)

    except Exception as e:
        print(f"[ERROR] Error initializing seed data: {e}")
        await session.rollback()
        raise


async def _seed_default_staff(session: AsyncSession) -> None:
    result = await session.execute(select(Staff))
    if result.scalars().first() is not None:
        return

    defaults = [
        Staff(name="Admin",  role=StaffRole.Admin,  hashed_pin=get_password_hash("0000")),
        Staff(name="Waiter", role=StaffRole.Waiter, hashed_pin=get_password_hash("1111")),
    ]
    for member in defaults:
        session.add(member)
    await session.commit()
    print("[OK] Default staff seeded: Admin (PIN: 0000), Waiter (PIN: 1111)")
