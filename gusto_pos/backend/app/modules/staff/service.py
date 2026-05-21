from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.users.model import User
from app.modules.roles.model import Role
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse, StaffProfile, StaffCreate, StaffUpdate
from app.core.security import verify_password, get_password_hash
from app.core.auth import create_access_token
import uuid

# Maps legacy StaffRole enum values to the new roles table names
_ROLE_MAP = {"Admin": "Owner", "Waiter": "Waiter", "Kitchen": "Kitchen"}


class StaffService:
    @staticmethod
    async def pin_login(db: AsyncSession, request: PinLoginRequest) -> PinLoginResponse | None:
        result = await db.execute(select(User).where(User.is_active == True))
        for user in result.scalars().all():
            if verify_password(request.pin, user.hashed_password):
                role = user.roles[0].name if user.roles else "Waiter"
                token = create_access_token(subject=str(user.id))
                return PinLoginResponse(
                    access_token=token,
                    staff=StaffProfile(id=user.id, name=user.username, role=role),
                )
        return None

    @staticmethod
    async def get_earnings_today(db: AsyncSession, staff_id: str) -> float:
        return 0.0

    @staticmethod
    async def get_all_with_earnings(db: AsyncSession) -> list[dict]:
        result = await db.execute(select(User).order_by(User.username))
        return [
            {
                "id": user.id,
                "name": user.username,
                "role": user.roles[0].name if user.roles else "Waiter",
                "assigned_table": None,
                "shift_start": None,
                "shift_end": None,
                "earnings_today": 0.0,
            }
            for user in result.scalars().all()
        ]

    @staticmethod
    async def create_staff(db: AsyncSession, payload: StaffCreate) -> dict:
        role_name = _ROLE_MAP.get(payload.role.value, "Waiter")
        user = User(
            username=payload.name,
            hashed_password=get_password_hash(payload.pin),
            is_active=True,
        )
        r = await db.execute(select(Role).where(Role.name == role_name))
        role = r.scalar_one_or_none()
        if role:
            user.roles = [role]
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return {
            "id": user.id,
            "name": user.username,
            "role": user.roles[0].name if user.roles else role_name,
            "assigned_table": None,
            "shift_start": None,
            "shift_end": None,
            "earnings_today": 0.0,
        }

    @staticmethod
    async def update_staff(db: AsyncSession, staff_id: str, payload: StaffUpdate) -> dict | None:
        r = await db.execute(select(User).where(User.id == uuid.UUID(staff_id)))
        user = r.scalar_one_or_none()
        if not user:
            return None
        return {
            "id": user.id,
            "name": user.username,
            "role": user.roles[0].name if user.roles else "Waiter",
            "assigned_table": None,
            "shift_start": None,
            "shift_end": None,
            "earnings_today": 0.0,
        }

    @staticmethod
    async def reset_pin(db: AsyncSession, staff_id: str, pin: str) -> bool:
        r = await db.execute(select(User).where(User.id == uuid.UUID(staff_id)))
        user = r.scalar_one_or_none()
        if not user:
            return False
        user.hashed_password = get_password_hash(pin)
        await db.commit()
        return True

    @staticmethod
    async def delete_staff(db: AsyncSession, staff_id: str) -> bool:
        r = await db.execute(select(User).where(User.id == uuid.UUID(staff_id)))
        user = r.scalar_one_or_none()
        if not user:
            return False
        await db.delete(user)
        await db.commit()
        return True
