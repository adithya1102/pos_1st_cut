from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.staff.model import Staff
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse, StaffProfile, StaffCreate
from app.core.security import verify_password, get_password_hash
from app.core.auth import create_access_token
import uuid


class StaffService:
    @staticmethod
    async def pin_login(db: AsyncSession, request: PinLoginRequest) -> PinLoginResponse | None:
        result = await db.execute(select(Staff))
        all_staff = result.scalars().all()

        for member in all_staff:
            if verify_password(request.pin, member.hashed_pin):
                token = create_access_token(subject=str(member.id))
                return PinLoginResponse(
                    access_token=token,
                    staff=StaffProfile.model_validate(member),
                )
        return None

    @staticmethod
    async def get_all(db: AsyncSession) -> list[Staff]:
        result = await db.execute(select(Staff).order_by(Staff.name))
        return list(result.scalars().all())

    @staticmethod
    async def create_staff(db: AsyncSession, payload: StaffCreate) -> Staff:
        member = Staff(
            name=payload.name,
            role=payload.role,
            hashed_pin=get_password_hash(payload.pin),
        )
        db.add(member)
        await db.commit()
        await db.refresh(member)
        return member

    @staticmethod
    async def reset_pin(db: AsyncSession, staff_id: str, pin: str) -> bool:
        result = await db.execute(select(Staff).where(Staff.id == uuid.UUID(staff_id)))
        member = result.scalars().first()
        if not member:
            return False
        member.hashed_pin = get_password_hash(pin)
        await db.commit()
        return True

    @staticmethod
    async def delete_staff(db: AsyncSession, staff_id: str) -> bool:
        result = await db.execute(select(Staff).where(Staff.id == uuid.UUID(staff_id)))
        member = result.scalars().first()
        if not member:
            return False
        await db.delete(member)
        await db.commit()
        return True
