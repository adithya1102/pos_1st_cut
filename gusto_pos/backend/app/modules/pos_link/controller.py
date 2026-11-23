"""POS registration link routes. Mounted under /api/v1 (app/main.py).

POST /owner/pos-registration-code -- owner auth, reuses
carevo_pos.deps.get_outlet_manager (the SAME allow-list /pos/* already uses;
there is no second auth path).

POST /pos-link/verify, POST /pos-link/consume -- PUBLIC, server-to-server.
No HMAC / shared secret (see service.py's module docstring for why); the
code's own entropy + TTL + single-use + rate limiting are the protection.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_pos.deps import get_outlet_manager
from app.modules.users.model import User
from app.modules.pos_link import schema as s_
from app.modules.pos_link.service import PosLinkService

router = APIRouter(tags=["POS Link"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/owner/pos-registration-code", response_model=s_.PosRegistrationCodeOut)
async def mint_pos_registration_code(
    staff: User = Depends(get_outlet_manager),
    db: AsyncSession = Depends(get_db),
):
    outlet_id = str(staff.outlet_id) if staff.outlet_id else None
    return await PosLinkService.mint_code(db, outlet_id)


@router.post("/pos-link/verify", response_model=s_.PosLinkVerifyOut)
async def verify_pos_link_code(
    payload: s_.PosLinkVerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await PosLinkService.verify(db, payload.code, _client_ip(request))


@router.post("/pos-link/consume", response_model=s_.PosLinkConsumeOut)
async def consume_pos_link_code(
    payload: s_.PosLinkConsumeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await PosLinkService.consume(
        db, payload.registration_ref, payload.pos_install_id, _client_ip(request)
    )
