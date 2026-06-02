import uuid
import random
import string
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.websocket_manager import pos_manager, waiter_manager
from app.modules.tables.models import TableSession
from app.modules.tables.schemas import TableSessionCreate, TableSessionResponse, TableSessionValidate
from app.modules.outlets.model import Table
from app.modules.orders.model import Order

router = APIRouter(prefix="/tables", tags=["Tables"])


def generate_token(length=6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


@router.get("/resolve")
async def resolve_session_token(t: str, db: AsyncSession = Depends(get_db)):
    """Resolve a session token → {outlet_id, table_id, zone}.

    The customer frontend calls this on every page load.  The token is the
    short code printed on the physical QR sticker (which encodes the session
    token generated when staff opens the table, not a static qr_token field).
    """
    token_upper = t.strip().upper()
    result = await db.execute(
        select(TableSession).where(
            TableSession.token == token_upper,
            TableSession.is_active == True,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=404,
            detail="Invalid QR code. Please scan the code on your table.",
        )
    return {
        "outlet_id": str(session.outlet_id),
        "table_id": session.table_id,
        "zone": session.zone or "normal",
    }


@router.post("/open", response_model=TableSessionResponse)
async def open_table(data: TableSessionCreate, db: AsyncSession = Depends(get_db)):
    """Staff opens a table — creates an active session with a fresh short token.
    The token is what gets encoded in the QR code shown to the customer.
    """
    # Close any existing active session for this table
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == data.outlet_id,
            TableSession.table_id == data.table_id,
            TableSession.is_active == True,
        )
    )
    for existing in result.scalars().all():
        existing.is_active = False
        existing.closed_at = datetime.utcnow()

    # Generate a unique session token (collision-safe)
    while True:
        token = generate_token()
        check = await db.execute(
            select(TableSession).where(
                TableSession.token == token, TableSession.is_active == True
            )
        )
        if not check.scalar_one_or_none():
            break

    session = TableSession(
        outlet_id=data.outlet_id,
        table_id=data.table_id,
        zone=data.zone,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=12),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    payload = {"table_id": str(data.table_id), "token": token}
    await pos_manager.broadcast_order_event(str(data.outlet_id), "TABLE_OPENED", payload)
    await waiter_manager.broadcast_order_event(str(data.outlet_id), "TABLE_OPENED", payload)

    return session


@router.post("/close/{table_id}")
async def close_table(table_id: str, outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Staff closes a table — session token immediately invalidated."""
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == outlet_id,
            TableSession.table_id == table_id,
            TableSession.is_active == True,
        )
    )
    for s in result.scalars().all():
        s.is_active = False
        s.closed_at = datetime.utcnow()
    await db.commit()

    payload = {"table_id": str(table_id)}
    await pos_manager.broadcast_order_event(str(outlet_id), "TABLE_CLOSED", payload)
    await waiter_manager.broadcast_order_event(str(outlet_id), "TABLE_CLOSED", payload)
    return {"message": f"Table {table_id} closed. Token invalidated."}


@router.get("/validate/{token}", response_model=TableSessionValidate)
async def validate_token(token: str, db: AsyncSession = Depends(get_db)):
    """Customer scans QR → validate the session token.

    The QR code encodes the short session token (set when staff opens the
    table).  There are no static qr_token fields any more — tokens are
    per-session and expire after 12 h.
    """
    token_upper = token.upper()

    result = await db.execute(
        select(TableSession).where(
            TableSession.token == token_upper,
            TableSession.is_active == True,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        return TableSessionValidate(
            token=token,
            table_id="",
            outlet_id="",
            is_valid=False,
            message="Invalid QR code. Please ask staff for assistance.",
        )

    if datetime.utcnow() > session.expires_at:
        session.is_active = False
        await db.commit()
        return TableSessionValidate(
            token=token,
            table_id=session.table_id,
            outlet_id=str(session.outlet_id),
            is_valid=False,
            message="Session expired. Ask your waiter to reopen the table.",
        )

    return TableSessionValidate(
        token=token,
        table_id=session.table_id,
        outlet_id=str(session.outlet_id),
        zone=session.zone or "normal",
        is_valid=True,
        message="Valid",
    )


@router.post("/cleanup")
async def cleanup_stale_tables(outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Reset table.status to 0 for tables that have status=1 but no active orders.

    Call this on POS startup to fix stale occupied flags left from a previous session.
    """
    tables_result = await db.execute(
        select(Table).where(Table.outlet_id == outlet_id, Table.status == 1)
    )
    stale_tables = tables_result.scalars().all()

    reset_count = 0
    for table in stale_tables:
        active_orders = await db.execute(
            select(Order).where(
                Order.table_id == table.table_number,
                Order.outlet_id == outlet_id,
                Order.order_status.notin_(["paid", "cancelled"]),
            ).limit(1)
        )
        if not active_orders.scalar_one_or_none():
            table.status = 0
            reset_count += 1

    await db.commit()
    return {"reset_count": reset_count, "message": f"Reset {reset_count} stale table(s) to free"}


@router.get("/all")
async def list_all_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TableSession))
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "token": s.token,
            "table_id": s.table_id,
            "outlet_id": str(s.outlet_id),
            "zone": s.zone,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
        }
        for s in sessions
    ]


@router.get("/active")
async def list_active_sessions(outlet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(TableSession).where(
            TableSession.outlet_id == outlet_id,
            TableSession.is_active == True,
        )
    )
    sessions = result.scalars().all()
    return [
        {
            "token": s.token,
            "table_id": s.table_id,
            "zone": s.zone,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        }
        for s in sessions
    ]
