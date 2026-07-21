"""CareVo Skip POS routes (staff-authenticated). Mounted under /api/v1."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_customer import schema as s
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.carevo_customer.service import CarevoService

router = APIRouter(prefix="/pos", tags=["CareVo Skip — POS"])


@router.post("/orders/verify-pickup", response_model=s.VerifyPickupOut)
async def verify_pickup(
    payload: s.VerifyPickupIn,
    _staff=Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    return await CarevoService.verify_pickup(db, payload.order_id, payload.pickup_code)
