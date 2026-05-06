from datetime import date
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.staff.model import Staff
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse, StaffProfile, StaffCreate, StaffUpdate
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
    async def get_earnings_today(db: AsyncSession, staff_id: str) -> float:
        from app.modules.orders.model import Order
        result = await db.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0.0))
            .where(
                Order.staff_id == uuid.UUID(staff_id),
                cast(Order.created_at, Date) == func.current_date(),
                Order.order_status.in_(["completed", "paid"]),
            )
        )
        return float(result.scalar() or 0.0)

    @staticmethod
    async def get_all_with_earnings(db: AsyncSession) -> list[dict]:
        members = await StaffService.get_all(db)
        result = []
        for member in members:
            earnings = await StaffService.get_earnings_today(db, str(member.id))
            result.append({
                "id": member.id,
                "name": member.name,
                "role": member.role,
                "assigned_table": member.assigned_table,
                "shift_start": member.shift_start,
                "shift_end": member.shift_end,
                "earnings_today": earnings,
            })
        return result

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
    async def update_staff(db: AsyncSession, staff_id: str, payload: StaffUpdate) -> Staff | None:
        result = await db.execute(select(Staff).where(Staff.id == uuid.UUID(staff_id)))
        member = result.scalars().first()
        if not member:
            return None
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(member, k, v)
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
