"""Business logic for the CareVo Admin Dashboard.

Follows CarevoService's raw-`text()` style deliberately: the new columns
(outlets.verification_status) and the new table (admin_audit_logs) are read and
written by SQL only, so NO existing ORM mapper (Outlet, User, Role) is modified.
That keeps the app importable and every existing flow byte-identical whether or
not migration 003 has been applied.

Every state-changing action writes one row to admin_audit_logs in the SAME
transaction as the change itself, so an audit gap cannot open.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.model import User

# outlets.verification_status lifecycle
PENDING = "pending_verification"
ACTIVE = "active"
REJECTED = "rejected"


class AdminService:
    # --------------------------- audit trail -------------------------------
    @staticmethod
    async def _audit(
        db: AsyncSession,
        actor: User,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        detail: Optional[dict] = None,
    ) -> None:
        """Append one admin_audit_logs row. Caller owns the commit."""
        await db.execute(
            text("""
                INSERT INTO admin_audit_logs
                    (actor_user_id, actor_username, action, target_type, target_id, detail)
                VALUES
                    (:actor_id, :actor_username, :action, :target_type, :target_id, CAST(:detail AS jsonb))
            """),
            {
                "actor_id": str(actor.id),
                "actor_username": actor.username,
                "action": action,
                "target_type": target_type,
                "target_id": str(target_id),
                "detail": json.dumps(detail) if detail is not None else None,
            },
        )

    # ----------------------------- outlets ---------------------------------
    @staticmethod
    async def list_outlets(
        db: AsyncSession, status_filter: Optional[str] = None
    ) -> list[dict]:
        """All outlets across all organizations, optionally filtered by status."""
        if status_filter is not None and status_filter not in (PENDING, ACTIVE, REJECTED):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status. Must be one of: {[PENDING, ACTIVE, REJECTED]}",
            )
        rows = (await db.execute(text("""
            SELECT o.id, o.location_name, o.city, o.organization_id,
                   org.name AS organization_name,
                   o.verification_status, o.is_visible, o.created_at
            FROM outlets o
            LEFT JOIN organizations org ON org.id = o.organization_id
            WHERE (:status IS NULL OR o.verification_status = :status)
            ORDER BY
                -- pending first: that is the queue the admin actually works
                CASE o.verification_status WHEN 'pending_verification' THEN 0 ELSE 1 END,
                o.created_at DESC NULLS LAST
        """), {"status": status_filter})).fetchall()
        return [
            {
                "id": r.id,
                "location_name": r.location_name,
                "city": r.city,
                "organization_id": r.organization_id,
                "organization_name": r.organization_name,
                "verification_status": r.verification_status,
                "is_visible": bool(r.is_visible),
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    async def _decide_outlet(
        db: AsyncSession,
        actor: User,
        outlet_id: uuid.UUID,
        target_status: str,
        reason: Optional[str],
    ) -> dict:
        current = (await db.execute(text(
            "SELECT id, verification_status FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not current:
            raise HTTPException(status_code=404, detail="Outlet not found")

        previous = current.verification_status
        if previous == target_status:
            raise HTTPException(
                status_code=409,
                detail=f"Outlet is already '{target_status}'",
            )

        row = (await db.execute(text("""
            UPDATE outlets SET verification_status = :s
            WHERE id = :oid
            RETURNING id, verification_status
        """), {"s": target_status, "oid": str(outlet_id)})).first()

        await AdminService._audit(
            db,
            actor,
            action=("outlet.approve" if target_status == ACTIVE else "outlet.reject"),
            target_type="outlet",
            target_id=outlet_id,
            detail={"from": previous, "to": target_status, "reason": reason},
        )
        await db.commit()
        return {
            "id": row[0],
            "verification_status": row[1],
            "previous_status": previous,
        }

    @staticmethod
    async def approve_outlet(
        db: AsyncSession, actor: User, outlet_id: uuid.UUID, reason: Optional[str]
    ) -> dict:
        return await AdminService._decide_outlet(db, actor, outlet_id, ACTIVE, reason)

    @staticmethod
    async def reject_outlet(
        db: AsyncSession, actor: User, outlet_id: uuid.UUID, reason: Optional[str]
    ) -> dict:
        return await AdminService._decide_outlet(db, actor, outlet_id, REJECTED, reason)

    # ------------------------- locked orders -------------------------------
    @staticmethod
    async def list_locked_orders(db: AsyncSession) -> list[dict]:
        """Every locked customer_order, across ALL outlets.

        Lockout comes from the existing 3-strike pickup_code flow
        (POST /pos/orders/verify-pickup -> HTTP 423). It is not auto-recoverable
        in v1; this is the supported manual recovery path.
        """
        rows = (await db.execute(text("""
            SELECT co.id, co.outlet_id, o.location_name AS outlet_name,
                   co.status, co.failed_attempts, co.total_amount,
                   c.phone_number AS customer_phone, co.created_at
            FROM customer_orders co
            LEFT JOIN outlets o   ON o.id = co.outlet_id
            LEFT JOIN customers c ON c.id = co.customer_id
            WHERE co.is_locked = true
            ORDER BY co.created_at DESC
        """))).fetchall()
        return [
            {
                "order_id": r.id,
                "outlet_id": r.outlet_id,
                "outlet_name": r.outlet_name,
                "status": r.status,
                "failed_attempts": r.failed_attempts or 0,
                "total_amount": float(r.total_amount) if r.total_amount is not None else 0.0,
                "customer_phone": r.customer_phone,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    async def unlock_order(
        db: AsyncSession, actor: User, order_id: uuid.UUID
    ) -> dict:
        """Clear the 3-strike lockout. Mirrors the manual UPDATE documented in
        OWNER_APP_README.md, but audited and gated behind SUPER_ADMIN."""
        current = (await db.execute(text(
            "SELECT id, is_locked, failed_attempts FROM customer_orders WHERE id = :oid"
        ), {"oid": str(order_id)})).first()
        if not current:
            raise HTTPException(status_code=404, detail="Order not found")
        if not current.is_locked:
            raise HTTPException(status_code=409, detail="Order is not locked")

        row = (await db.execute(text("""
            UPDATE customer_orders
            SET is_locked = false, failed_attempts = 0
            WHERE id = :oid
            RETURNING id, is_locked, failed_attempts
        """), {"oid": str(order_id)})).first()

        await AdminService._audit(
            db,
            actor,
            action="order.unlock",
            target_type="customer_order",
            target_id=order_id,
            detail={"failed_attempts_cleared": current.failed_attempts},
        )
        await db.commit()
        return {
            "order_id": row[0],
            "is_locked": bool(row[1]),
            "failed_attempts": row[2],
        }

    # --------------------------- audit log ---------------------------------
    @staticmethod
    async def list_audit_logs(db: AsyncSession, limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        rows = (await db.execute(text("""
            SELECT id, actor_username, action, target_type, target_id, detail, created_at
            FROM admin_audit_logs
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"lim": limit})).fetchall()
        return [
            {
                "id": r.id,
                "actor_username": r.actor_username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "created_at": r.created_at,
            }
            for r in rows
        ]
