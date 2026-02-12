from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sync_logs.schema import SyncLogRead
from app.modules.sync_logs.model import SyncLog
from app.core.dependencies import get_db_dep

router = APIRouter(prefix="/sync-logs", tags=["sync_logs"])


@router.get("/", response_model=list[SyncLogRead])
async def list_sync_logs(db: AsyncSession = get_db_dep()):
    result = await db.execute(select(SyncLog))
    return result.scalars().all()


@router.get("/{item_id}", response_model=SyncLogRead)
async def get_sync_log(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(SyncLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync log not found")
    return obj


@router.post("/", response_model=SyncLogRead, status_code=status.HTTP_201_CREATED)
async def create_sync_log(payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = SyncLog(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.put("/{item_id}", response_model=SyncLogRead)
async def update_sync_log(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = get_db_dep()):
    obj = await db.get(SyncLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync log not found")
    for k, v in payload.items():
        setattr(obj, k, v)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync_log(item_id: UUID, db: AsyncSession = get_db_dep()):
    obj = await db.get(SyncLog, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync log not found")
    await db.delete(obj)
    await db.commit()
