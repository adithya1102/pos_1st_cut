from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.carevo_admin.deps import is_super_admin
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.staff.service import StaffService
from app.modules.staff.schema import StaffCreate, StaffRead, StaffUpdate, ResetPinRequest
from app.modules.users.model import User

router = APIRouter(prefix="/staff")

# Roles permitted to reset SOMEONE ELSE'S PIN. Owner/Manager are the two names
# the seeded roles table uses for "runs this outlet"; SUPER_ADMIN is handled by
# is_super_admin rather than by name-matching here.
_PIN_ADMIN_ROLES = {"OWNER", "MANAGER", "ADMIN"}


def _may_reset_pin(actor: User, target_staff_id: str) -> bool:
    """Either it is your own PIN, or you hold a role that administers others'.

    Self-service is allowed because a staff member changing their own PIN is
    the ordinary case and needs no privilege; anything else is an
    administrative act over another person's credential.
    """
    if str(actor.id) == str(target_staff_id):
        return True
    if is_super_admin(actor):
        return True
    return any((r.name or "").upper() in _PIN_ADMIN_ROLES for r in (actor.roles or []))


@router.get("/", response_model=list[StaffRead])
async def list_staff(db: AsyncSession = Depends(get_db)):
    return await StaffService.get_all_with_earnings(db)


@router.post("/", response_model=StaffRead, status_code=201)
async def create_staff(payload: StaffCreate, db: AsyncSession = Depends(get_db)):
    return await StaffService.create_staff(db, payload)


@router.put("/{staff_id}", response_model=StaffRead)
async def update_staff(staff_id: str, payload: StaffUpdate, db: AsyncSession = Depends(get_db)):
    member = await StaffService.update_staff(db, staff_id, payload)
    if not member:
        raise HTTPException(status_code=404, detail="Staff not found")
    return member


@router.put("/{staff_id}/pin")
async def reset_pin(
    staff_id: str,
    payload: ResetPinRequest,
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Reset a staff PIN. AUTHENTICATED, and authorised per-target.

    This endpoint was completely unauthenticated. StaffService.reset_pin writes
    users.hashed_password — the staff LOGIN credential, not a secondary PIN —
    so an anonymous caller who knew a staff id could overwrite that credential
    and then obtain a real staff JWT from /auth/login. Verified end to end
    against a live server before this change: PUT returned 200 {"ok":true}, the
    stored hash stopped verifying the old PIN and started verifying the
    attacker's, and /auth/login then issued a token.

    Two gates, in this order:
      401 — no/!staff token (get_current_staff).
      403 — authenticated, but neither the owner of this PIN nor a role that
            administers other people's credentials.

    The id check runs BEFORE the existence check on purpose: answering 404 for
    an id that exists but is not yours would let any authenticated staff member
    enumerate staff ids. A non-admin gets 403 whether or not the target exists.
    """
    if not _may_reset_pin(actor, staff_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only reset your own PIN",
        )
    ok = await StaffService.reset_pin(db, staff_id, payload.pin)
    if not ok:
        raise HTTPException(status_code=404, detail="Staff not found")
    return {"ok": True}


@router.delete("/{staff_id}")
async def delete_staff(staff_id: str, db: AsyncSession = Depends(get_db)):
    ok = await StaffService.delete_staff(db, staff_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Staff not found")
    return {"ok": True}
