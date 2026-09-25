from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
# Ensure you have an AuditLogRead schema defined in your schema.py
from app.modules.audit_logs.schema import AuditLogRead 
from app.modules.audit_logs.service import AuditLogService
from app.modules.carevo_customer.deps import get_current_staff


# STAFF-ONLY, ROUTER-WIDE.
#
# Every route in this file was reachable with no credentials at all. A caller
# audit across GustoPOS, GustoWaiter, admin_app, owner_app, customer_app,
# gusto_pos/customer_app, dashboard_app and mcp_server found NOTHING calling
# /audit-logs — which is what makes closing it router-wide safe here, where the
# same change on orders/ or menus/ would take the tills offline.
#
# Applied on the ROUTER rather than per route, matching customers/ and
# outlets/: a per-route list is a list someone can forget to extend, and the
# next endpoint added to this file would be born unauthenticated.
#
# Exposed before this change: the audit trail — readable, and appendable, which lets a caller forge entries.
router = APIRouter(prefix="/audit-logs", dependencies=[Depends(get_current_staff)])

@router.get("/", response_model=list[AuditLogRead])
async def list_audit_logs(db: AsyncSession = Depends(get_db)):
    return await AuditLogService.get_all_audit_logs(db)

@router.get("/{item_id}", response_model=AuditLogRead)
async def get_audit_log(item_id: UUID, db: AsyncSession = Depends(get_db)):
    obj = await AuditLogService.get_audit_log_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return obj

@router.post("/", response_model=AuditLogRead, status_code=status.HTTP_201_CREATED)
async def create_audit_log(payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)):
    return await AuditLogService.create_audit_log(db, payload)