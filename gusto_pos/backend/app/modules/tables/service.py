import random
import string
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.websocket_manager import manager, pos_manager, waiter_manager
from app.modules.orders.model import Order
from app.modules.orders.service import fire
from app.modules.outlets.model import Table
from app.modules.tables.models import TableSession
from app.modules.tables.schemas import TableSessionCreate, TableSessionValidate


def generate_token(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


class TableService:
    @staticmethod
    async def resolve_token(db: AsyncSession, token: str) -> dict:
        """Resolve a session token → {outlet_id, table_id, zone}."""
        result = await db.execute(
            select(TableSession).where(
                TableSession.token == token.strip().upper(),
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

    @staticmethod
    async def open_table(db: AsyncSession, data: TableSessionCreate) -> TableSession:
        """Staff opens a table — closes any stale session and mints a fresh QR token."""
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
                    TableSession.token == token,
                    TableSession.is_active == True,
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

        outlet_id = str(data.outlet_id)
        payload = {"table_id": str(data.table_id), "token": token}
        await pos_manager.broadcast_order_event(outlet_id, "TABLE_OPENED", payload)
        await waiter_manager.broadcast_order_event(outlet_id, "TABLE_OPENED", payload)

        table_update = {
            "type": "table_update",
            "table_id": str(data.table_id),
            "status": "occupied",
            "token": token,
        }
        fire(manager.notify_pos(outlet_id, table_update))
        fire(manager.notify_waiters(outlet_id, table_update))

        return session

    @staticmethod
    async def close_table(db: AsyncSession, table_id: str, outlet_id: uuid.UUID) -> dict:
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

        outlet = str(outlet_id)
        await pos_manager.broadcast_order_event(outlet, "TABLE_CLOSED", {"table_id": str(table_id)})
        await waiter_manager.broadcast_order_event(outlet, "TABLE_CLOSED", {"table_id": str(table_id)})

        table_update = {"type": "table_update", "table_id": str(table_id), "status": "free"}
        fire(manager.notify_pos(outlet, table_update))
        fire(manager.notify_waiters(outlet, table_update))
        fire(manager.notify_customer(str(table_id), {
            "type": "session_closed",
            "message": "Thank you for dining with us!",
        }))

        return {"message": f"Table {table_id} closed. Token invalidated."}

    @staticmethod
    async def validate_token(db: AsyncSession, token: str) -> TableSessionValidate:
        """Customer scans QR → validate the session token."""
        result = await db.execute(
            select(TableSession).where(
                TableSession.token == token.upper(),
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

    @staticmethod
    async def cleanup_stale_tables(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        """Reset table.status to 0 for tables flagged occupied but holding no active orders."""
        tables_result = await db.execute(
            select(Table).where(Table.outlet_id == outlet_id, Table.status == 1)
        )
        reset_count = 0
        for table in tables_result.scalars().all():
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

    @staticmethod
    async def list_all_sessions(db: AsyncSession) -> list[dict]:
        result = await db.execute(select(TableSession))
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
            for s in result.scalars().all()
        ]

    @staticmethod
    async def list_active_sessions(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        result = await db.execute(
            select(TableSession).where(
                TableSession.outlet_id == outlet_id,
                TableSession.is_active == True,
            )
        )
        return [
            {
                "token": s.token,
                "table_id": s.table_id,
                "zone": s.zone,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            }
            for s in result.scalars().all()
        ]
