import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.tables.schemas import (
    TableSessionCreate, TableSessionResponse, TableSessionValidate,
)
from app.modules.tables.service import TableService

router = APIRouter(prefix="/tables", tags=["Tables"])


@router.get("/resolve")
async def resolve_session_token(t: str, db: AsyncSession = Depends(get_db)):
    """Resolve the short code on the table's QR sticker → outlet, table and zone."""
    return await TableService.resolve_token(db, t)


@router.post("/open", response_model=TableSessionResponse)
async def open_table(data: TableSessionCreate, db: AsyncSession = Depends(get_db)):
    """Staff opens a table — creates an active session with a fresh short token."""
    return await TableService.open_table(db, data)


@router.post("/close/{table_id}")
async def close_table(table_id: str, outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Staff closes a table — session token immediately invalidated."""
    return await TableService.close_table(db, table_id, outlet_id)


@router.get("/validate/{token}", response_model=TableSessionValidate)
async def validate_token(token: str, db: AsyncSession = Depends(get_db)):
    """Customer scans QR → validate the session token."""
    return await TableService.validate_token(db, token)


@router.post("/cleanup")
async def cleanup_stale_tables(outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Reset stale occupied flags. Call on POS startup."""
    return await TableService.cleanup_stale_tables(db, outlet_id)


@router.get("/all")
async def list_all_sessions(db: AsyncSession = Depends(get_db)):
    return await TableService.list_all_sessions(db)


@router.get("/active")
async def list_active_sessions(outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await TableService.list_active_sessions(db, outlet_id)
