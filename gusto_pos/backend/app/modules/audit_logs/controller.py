from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit_logs.schema import AuditLogRead
from app.modules.audit_logs.model import AuditLog
from app.core.dependencies import get_db_dep

# FIXED: Removed prefix and tags
router = APIRouter()

@router.get("/", response_model=list[AuditLogRead])
async def list_audit_logs(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(AuditLog))
    return result.scalars().all()

@router.get("/{item_id}", response_model=AuditLogRead)
async def get_audit_log(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(AuditLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return obj

@router.post("/", response_model=AuditLogRead, status_code=status.HTTP_201_CREATED)
async def create_audit_log(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = AuditLog(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.put("/{item_id}", response_model=AuditLogRead)
async def update_audit_log(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(AuditLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_audit_log(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(AuditLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    await db.delete(obj)
    await db.commit()