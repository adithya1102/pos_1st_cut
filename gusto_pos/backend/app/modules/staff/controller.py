from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.staff.service import StaffService
from app.modules.staff.schema import StaffCreate, StaffRead, StaffUpdate, ResetPinRequest

router = APIRouter(prefix="/staff")


@router.get("/", response_model=list[StaffRead])
async def list_staff(db: AsyncSession = Depends(get_db)):
    return await StaffService.get_all_with_earnings(db)


@router.post("/", response_model=StaffRead, status_code=201)
async def create_staff(payload: StaffCreate, db: AsyncSession = Depends(get_db)):
    member = await StaffService.create_staff(db, payload)
    return StaffRead(
        id=member.id,
        name=member.name,
        role=member.role,
        assigned_table=member.assigned_table,
        shift_start=member.shift_start,
        shift_end=member.shift_end,
        earnings_today=0.0,
    )


@router.put("/{staff_id}", response_model=StaffRead)
async def update_staff(staff_id: str, payload: StaffUpdate, db: AsyncSession = Depends(get_db)):
    member = await StaffService.update_staff(db, staff_id, payload)
    if not member:
        raise HTTPException(status_code=404, detail="Staff not found")
    earnings = await StaffService.get_earnings_today(db, staff_id)
    return StaffRead(
        id=member.id,
        name=member.name,
        role=member.role,
        assigned_table=member.assigned_table,
        shift_start=member.shift_start,
        shift_end=member.shift_end,
        earnings_today=earnings,
    )


@router.put("/{staff_id}/pin")
async def reset_pin(staff_id: str, payload: ResetPinRequest, db: AsyncSession = Depends(get_db)):
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
