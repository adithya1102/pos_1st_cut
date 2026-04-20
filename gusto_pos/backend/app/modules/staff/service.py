from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.staff.model import Staff
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse, StaffProfile
from app.core.security import verify_password
from app.core.auth import create_access_token


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
