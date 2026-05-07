import uuid
import random
import string
import hashlib
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.modules.tables.models import TableSession
from app.modules.outlets.model import Table
from app.modules.tables.schemas import TableSessionCreate, TableSessionResponse, TableSessionValidate

router = APIRouter(prefix="/tables", tags=["Tables"])

def generate_token(length=6):
    """Generate a short alphanumeric token like A3K9PX"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def generate_static_qr_token(outlet_id: str, table_number: int) -> str:
    """Generate a deterministic permanent QR token from outlet + table number.
    Same inputs always produce the same token — safe for printed QR codes."""
    raw = f"{outlet_id}-table-{table_number}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8].upper()


@router.post("/open", response_model=TableSessionResponse)
async def open_table(data: TableSessionCreate, db: AsyncSession = Depends(get_db)):
    """Staff opens a table — creates a session (QR token is static, session is internal)"""
    
    # Close any existing active session for this table
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == data.outlet_id,
            TableSession.table_id == data.table_id,
            TableSession.is_active == True
        )
    )
    existing = result.scalars().all()
    for session in existing:
        session.is_active = False
        session.closed_at = datetime.utcnow()

    # Generate unique internal token for this session
    while True:
        token = generate_token()
        check = await db.execute(select(TableSession).where(TableSession.token == token, TableSession.is_active == True))
        if not check.scalar_one_or_none():
            break

    session = TableSession(
        outlet_id=data.outlet_id,
        table_id=data.table_id,
        zone=data.zone,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=12)
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session

@router.post("/close/{table_id}")
async def close_table(table_id: str, outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Staff closes a table — token immediately invalidated"""
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == outlet_id,
            TableSession.table_id == table_id,
            TableSession.is_active == True
        )
    )
    sessions = result.scalars().all()
    for s in sessions:
        s.is_active = False
        s.closed_at = datetime.utcnow()
    await db.commit()
    return {"message": f"Table {table_id} closed. Token invalidated."}

@router.get("/validate/{token}", response_model=TableSessionValidate)
async def validate_token(token: str, db: AsyncSession = Depends(get_db)):
    """Customer scans QR → validates static token → checks for active session.
    
    Flow:
    1. Look up the permanent Table record by qr_token
    2. If found, check if there's an active TableSession for that table
    3. If no active session, tell customer to ask waiter to open the table
    4. Fall back to old dynamic token lookup for backward compatibility
    """
    token_upper = token.upper()

    # ── Step 1: Check if this is a STATIC QR token (permanent, printed on table) ──
    table_result = await db.execute(
        select(Table).where(Table.qr_token == token_upper)
    )
    table = table_result.scalar_one_or_none()

    if table:
        # Found a physical table — now check for active session
        table_id = f"T-{table.table_number}"
        outlet_id = str(table.outlet_id)

        session_result = await db.execute(
            select(TableSession).where(
                TableSession.outlet_id == table.outlet_id,
                TableSession.table_id == table_id,
                TableSession.is_active == True
            )
        )
        session = session_result.scalar_one_or_none()

        if not session:
            return TableSessionValidate(
                token=token, table_id=table_id, outlet_id=outlet_id,
                is_valid=False,
                message="Table not active. Ask your waiter to open the table."
            )

        if datetime.utcnow() > session.expires_at:
            session.is_active = False
            await db.commit()
            return TableSessionValidate(
                token=token, table_id=table_id, outlet_id=outlet_id,
                is_valid=False,
                message="Session expired. Ask your waiter to reopen the table."
            )

        return TableSessionValidate(
            token=token,
            table_id=table_id,
            outlet_id=outlet_id,
            zone=session.zone or "normal",
            is_valid=True,
            message="Valid"
        )

    # ── Step 2: Fall back to old dynamic token lookup (backward compat) ──
    result = await db.execute(
        select(TableSession).where(
            TableSession.token == token_upper,
            TableSession.is_active == True
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        return TableSessionValidate(
            token=token, table_id="", outlet_id="",
            is_valid=False, message="Invalid QR code. Please ask staff for assistance."
        )

    if datetime.utcnow() > session.expires_at:
        session.is_active = False
        await db.commit()
        return TableSessionValidate(
            token=token, table_id="", outlet_id="",
            is_valid=False, message="Session expired. Ask your waiter to reopen the table."
        )

    return TableSessionValidate(
        token=token,
        table_id=session.table_id,
        outlet_id=str(session.outlet_id),
        zone=session.zone or "normal",
        is_valid=True,
        message="Valid"
    )

@router.get("/all")
async def list_all_sessions(db: AsyncSession = Depends(get_db)):
    """List all table sessions (for debugging/admin)"""
    result = await db.execute(select(TableSession))
    sessions = result.scalars().all()
    return [
        {
            "id": str(session.id),
            "token": session.token,
            "table_id": session.table_id,
            "outlet_id": str(session.outlet_id),
            "is_active": session.is_active,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
        }
        for session in sessions
    ]

@router.get("/active")
async def list_active_sessions(outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List only active table sessions for a specific outlet"""
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == outlet_id,
            TableSession.is_active == True
        )
    )
    sessions = result.scalars().all()
    return [
        {
            "token": session.token,
            "table_id": session.table_id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        }
        for session in sessions
    ]
