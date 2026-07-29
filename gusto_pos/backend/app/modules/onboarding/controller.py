"""Public owner self-signup. Unauthenticated + rate-limited (per IP).
Mounted under /api/v1 → POST /api/v1/register."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_customer import schema as s
from app.modules.carevo_customer.service import CarevoService

router = APIRouter(tags=["Onboarding"])


@router.post("/register", response_model=s.RegisterOut, status_code=201)
async def register(
    payload: s.RegisterIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    return await CarevoService.register_owner(db, payload, client_ip)
