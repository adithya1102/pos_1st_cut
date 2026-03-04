from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.sync_logs.schema import SyncLogRead  # Ensure you have this schema
from app.modules.sync_logs.service import SyncLogService

router = APIRouter(prefix="/sync-logs")

@router.get("/", response_model=list[SyncLogRead])
async def list_sync_logs(db: AsyncSession = Depends(get_db)):
    return await SyncLogService.get_all_sync_logs(db)

@router.get("/{item_id}", response_model=SyncLogRead)
async def get_sync_log(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await SyncLogService.get_sync_log_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync Log not found")
    return obj

@router.post("/", response_model=SyncLogRead, status_code=status.HTTP_201_CREATED)
async def create_sync_log(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await SyncLogService.create_sync_log(db, payload)

@router.put("/{item_id}", response_model=SyncLogRead)
async def update_sync_log(item_id: UUID, payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    obj = await SyncLogService.update_sync_log(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync Log not found")
    return obj

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync_log(item_id: UUID, db: AsyncSession = Depends(get_db)):
    if not await SyncLogService.delete_sync_log(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sync Log not found")