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
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.model import User

# ---------------------------------------------------------------------------
# Activity heuristic (NOT a churn model, NOT a prediction).
#
# This is a fixed recency bucket: days since the customer's last PAID order,
# compared against two constants. It has no training data, no features beyond
# recency, and no probability output — it cannot say a customer WILL churn, only
# that they have not ordered in N days. Deliberately kept this dumb: the order
# volume here is far too low for a fitted model to mean anything, and a fake
# confidence score would be worse than an honest one.
#
# Thresholds are arbitrary-but-reasonable for food ordering; change freely.
ACTIVITY_ACTIVE_MAX_DAYS = 14      # ordered within 2 weeks
ACTIVITY_AT_RISK_MAX_DAYS = 30     # 14-30 days
# Beyond 30 days -> "Churned". Never ordered -> "No orders".

# outlets.verification_status lifecycle
PENDING = "pending_verification"
ACTIVE = "active"
REJECTED = "rejected"


def _days_since(last_order_at) -> Optional[int]:
    """Whole days since [last_order_at]. None when the customer never ordered."""
    if last_order_at is None:
        return None
    ts = last_order_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - ts).days, 0)


def _activity(last_order_at) -> str:
    """Bucket a customer by order recency. A HEURISTIC LABEL, not a prediction.

    Returns one of: "No orders" | "Active" | "At Risk" | "Churned".
    """
    days = _days_since(last_order_at)
    if days is None:
        return "No orders"
    if days <= ACTIVITY_ACTIVE_MAX_DAYS:
        return "Active"
    if days <= ACTIVITY_AT_RISK_MAX_DAYS:
        return "At Risk"
    return "Churned"


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
            SELECT o.id, o.location_name, o.city, o.phone_number, o.organization_id,
                   org.name AS organization_name,
                   o.verification_status, o.is_visible, o.created_at,
                   o.deactivated_at
            FROM outlets o
            LEFT JOIN organizations org ON org.id = o.organization_id
            -- CAST is required: with a NULL bind, Postgres cannot infer the
            -- parameter's type from `:status IS NULL` alone and aborts the
            -- statement with AmbiguousParameterError.
            WHERE (CAST(:status AS varchar) IS NULL
                   OR o.verification_status = CAST(:status AS varchar))
            ORDER BY
                -- live before deactivated, then pending first (the work queue)
                CASE WHEN o.deactivated_at IS NULL THEN 0 ELSE 1 END,
                CASE o.verification_status WHEN 'pending_verification' THEN 0 ELSE 1 END,
                o.created_at DESC NULLS LAST
        """), {"status": status_filter})).fetchall()
        return [
            {
                "id": r.id,
                "location_name": r.location_name,
                "city": r.city,
                "phone_number": r.phone_number,
                "organization_id": r.organization_id,
                "organization_name": r.organization_name,
                "verification_status": r.verification_status,
                "is_visible": bool(r.is_visible),
                "created_at": r.created_at,
                "deactivated_at": r.deactivated_at,
                "is_deactivated": r.deactivated_at is not None,
            }
            for r in rows
        ]

    # --------------------- soft-delete (deactivate) ------------------------
    @staticmethod
    async def deactivate_outlet(
        db: AsyncSession, actor: User, outlet_id: uuid.UUID, reason: Optional[str]
    ) -> dict:
        """Soft-delete: hide the outlet everywhere customer-facing (also forces
        is_visible=false) but keep every row — orders, events, outcomes stay as
        permanent training data. Reversible via reactivate_outlet."""
        current = (await db.execute(text(
            "SELECT id, deactivated_at, is_visible FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not current:
            raise HTTPException(status_code=404, detail="Outlet not found")
        if current.deactivated_at is not None:
            raise HTTPException(status_code=409, detail="Outlet is already deactivated")

        row = (await db.execute(text("""
            UPDATE outlets
            SET deactivated_at = now(), is_visible = false
            WHERE id = :oid
            RETURNING id, deactivated_at
        """), {"oid": str(outlet_id)})).first()

        await AdminService._audit(
            db, actor, action="outlet.deactivate", target_type="outlet",
            target_id=outlet_id,
            detail={"reason": reason, "was_visible": bool(current.is_visible)},
        )
        await db.commit()
        return {"id": row[0], "is_deactivated": True, "deactivated_at": row[1]}

    @staticmethod
    async def reactivate_outlet(
        db: AsyncSession, actor: User, outlet_id: uuid.UUID
    ) -> dict:
        """Undo a soft-delete. Leaves is_visible false — the owner re-enables
        customer visibility themselves, so reactivation never silently re-lists."""
        current = (await db.execute(text(
            "SELECT id, deactivated_at FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not current:
            raise HTTPException(status_code=404, detail="Outlet not found")
        if current.deactivated_at is None:
            raise HTTPException(status_code=409, detail="Outlet is not deactivated")

        row = (await db.execute(text("""
            UPDATE outlets SET deactivated_at = NULL
            WHERE id = :oid
            RETURNING id, deactivated_at
        """), {"oid": str(outlet_id)})).first()

        await AdminService._audit(
            db, actor, action="outlet.reactivate", target_type="outlet",
            target_id=outlet_id, detail=None,
        )
        await db.commit()
        return {"id": row[0], "is_deactivated": False, "deactivated_at": row[1]}

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

    # ------------------------- customer directory --------------------------
    @staticmethod
    async def list_customers(db: AsyncSession, limit: int = 200) -> list[dict]:
        """Read-only customer directory across ALL outlets.

        Order count is a LEFT JOIN aggregate so customers who signed in but
        never ordered still appear (count 0) — they are exactly the rows worth
        seeing. No PII beyond the phone number and email the customer signed in
        with, and no write path: this endpoint is deliberately GET-only.

        Since migration 008 either identifier can be NULL: phone-only customers
        (OTP) have no email, Google-only customers have no phone. Both columns
        are surfaced so a row is never blank in both.
        """
        # Aggregates are computed in SQL rather than per-customer round trips:
        # one pass over PAID orders for the money/recency figures, plus two
        # DISTINCT ON pre-aggregates for the "most X" columns. Only PAID orders
        # count - an abandoned basket is not a purchase and must not inflate
        # lifetime value or make a lapsed customer look active.
        rows = (await db.execute(text("""
            WITH paid AS (
                SELECT co.id, co.customer_id, co.outlet_id, co.total_amount,
                       co.created_at
                FROM customer_orders co
                WHERE co.payment_status = 'PAID'
            ),
            money AS (
                SELECT customer_id,
                       count(*)               AS paid_order_count,
                       sum(total_amount)      AS total_order_value,
                       max(created_at)        AS last_order_at
                FROM paid GROUP BY customer_id
            ),
            top_dish AS (
                SELECT DISTINCT ON (p.customer_id)
                       p.customer_id, coi.name_snap AS dish_name,
                       sum(coi.quantity) AS qty
                FROM paid p
                JOIN customer_order_items coi ON coi.customer_order_id = p.id
                WHERE coi.name_snap IS NOT NULL
                GROUP BY p.customer_id, coi.name_snap
                ORDER BY p.customer_id, qty DESC, coi.name_snap
            ),
            top_outlet AS (
                SELECT DISTINCT ON (p.customer_id)
                       p.customer_id, o.location_name AS outlet_name,
                       count(*) AS visits
                FROM paid p
                LEFT JOIN outlets o ON o.id = p.outlet_id
                GROUP BY p.customer_id, o.location_name
                ORDER BY p.customer_id, visits DESC, o.location_name
            )
            SELECT c.id, c.phone_number, c.email, c.name, c.created_at,
                   c.points_balance, c.premium_until,
                   count(co.id)                       AS order_count,
                   COALESCE(m.total_order_value, 0)   AS total_order_value,
                   m.last_order_at,
                   td.dish_name                       AS top_dish,
                   tou.outlet_name                    AS top_outlet
            FROM customers c
            LEFT JOIN customer_orders co ON co.customer_id = c.id
            LEFT JOIN money      m   ON m.customer_id   = c.id
            LEFT JOIN top_dish   td  ON td.customer_id  = c.id
            LEFT JOIN top_outlet tou ON tou.customer_id = c.id
            -- Hide deleted accounts. A deleted customer is anonymised in place
            -- rather than removed (customer_orders.customer_id is RESTRICT), so
            -- the row survives to hold order history together. It holds no
            -- personal data any more and is not a person an admin can act on,
            -- so listing it would be noise at best and misleading at worst.
            -- The tombstone lives in google_uid — see DELETED_UID_PREFIX.
            WHERE c.google_uid IS NULL OR c.google_uid NOT LIKE 'deleted:%'
            GROUP BY c.id, c.phone_number, c.email, c.name, c.created_at,
                     c.points_balance, c.premium_until,
                     m.total_order_value, m.last_order_at, td.dish_name,
                     tou.outlet_name
            ORDER BY c.created_at DESC NULLS LAST
            LIMIT :limit
        """), {"limit": limit})).fetchall()
        now = datetime.now(timezone.utc)

        def _plan(premium_until) -> str:
            # Derived, never stored — mirrors CarevoService._plan_label so the
            # admin view and the customer's own view can never disagree.
            if premium_until is None:
                return "Free"
            if premium_until.tzinfo is None:
                premium_until = premium_until.replace(tzinfo=timezone.utc)
            return "Premium" if premium_until > now else "Free"

        return [
            {
                "id": r.id,
                "phone_number": r.phone_number,
                "email": r.email,
                "name": r.name,
                "order_count": r.order_count or 0,
                "created_at": r.created_at,
                "points_balance": float(r.points_balance or 0),
                "premium_until": r.premium_until,
                "plan": _plan(r.premium_until),
                "total_order_value": float(r.total_order_value or 0),
                "top_dish": r.top_dish,
                "top_outlet": r.top_outlet,
                "last_order_at": r.last_order_at,
                "days_since_last_order": _days_since(r.last_order_at),
                "activity_status": _activity(r.last_order_at),
            }
            for r in rows
        ]

    # ---------------- prediction engine (shadow-mode observability) --------
    # Read-only windows onto the PE tables from migration 006. Raw SQL, no ORM,
    # every order FK points at customer_orders(id). Graduation is intentionally
    # NOT implemented here (Build Order Step 7) — shadow_mode is reported as-is.
    GRADUATION_THRESHOLD = 300

    @staticmethod
    async def prediction_overview(db: AsyncSession) -> dict:
        """FR-A3 (shadow-mode status) + FR-A4 (global data health)."""
        r = (await db.execute(text("""
            SELECT
              (SELECT count(*) FROM order_outcome)                          AS outcomes,
              (SELECT count(*) FROM order_outcome WHERE promise_kept)       AS kept,
              (SELECT count(*) FROM order_outcome WHERE travel_trust >= 0.5) AS trusted_travel,
              (SELECT count(*) FROM order_outcome WHERE kitchen_trust > 0)   AS trusted_kitchen,
              (SELECT count(*) FROM order_events)                           AS events,
              (SELECT count(DISTINCT order_id) FROM prediction_log)         AS predicted_orders,
              (SELECT round(avg(interval_score), 1) FROM order_outcome)     AS avg_interval,
              (SELECT count(*) FROM outlet_reliability WHERE NOT shadow_mode) AS graduated_outlets
        """))).first()
        outcomes = r.outcomes or 0
        threshold = AdminService.GRADUATION_THRESHOLD
        return {
            # Shadow mode is a hard product state in this build, not a per-outlet
            # decision — Steps 6-8/10 (real Maps, graduation, JIT, GBM) are out.
            "shadow_mode": True,
            "read_only": True,
            "graduation_threshold": threshold,
            "orders_analyzed": outcomes,
            "progress_pct": min(100.0, round(outcomes / threshold * 100, 1)) if threshold else 0.0,
            "promise_kept": r.kept or 0,
            "promise_kept_rate": round((r.kept or 0) / outcomes, 3) if outcomes else None,
            "trusted_travel_observations": r.trusted_travel or 0,
            "trusted_kitchen_observations": r.trusted_kitchen or 0,
            "total_events": r.events or 0,
            "orders_predicted": r.predicted_orders or 0,
            "avg_interval_score": float(r.avg_interval) if r.avg_interval is not None else None,
            "graduated_outlets": r.graduated_outlets or 0,
        }

    @staticmethod
    async def prediction_outlets(db: AsyncSession) -> list[dict]:
        """FR-A2 — per-outlet prediction quality. Only outlets with a completed
        outcome appear (reliability is written alongside outcomes)."""
        rows = (await db.execute(text("""
            SELECT o.id, o.location_name,
                   count(oo.order_id)                                    AS outcomes,
                   count(oo.order_id) FILTER (WHERE oo.promise_kept)     AS kept,
                   round(avg(oo.interval_score), 1)                      AS avg_interval,
                   round(avg(oo.kitchen_trust), 2)                       AS avg_kitchen_trust,
                   round(avg(oo.travel_trust), 2)                        AS avg_travel_trust,
                   round(avg(oo.customer_trust), 2)                      AS avg_customer_trust,
                   r.trusted_order_count, r.tap_discipline, r.shadow_mode
            FROM outlets o
            JOIN order_outcome oo       ON oo.outlet_id = o.id
            LEFT JOIN outlet_reliability r ON r.outlet_id = o.id
            GROUP BY o.id, o.location_name, r.trusted_order_count,
                     r.tap_discipline, r.shadow_mode
            ORDER BY outcomes DESC
        """))).fetchall()
        return [
            {
                "outlet_id": r.id,
                "outlet_name": r.location_name,
                "outcomes": r.outcomes,
                "promise_kept": r.kept,
                "promise_kept_rate": round(r.kept / r.outcomes, 3) if r.outcomes else None,
                "avg_interval_score": float(r.avg_interval) if r.avg_interval is not None else None,
                "avg_kitchen_trust": float(r.avg_kitchen_trust) if r.avg_kitchen_trust is not None else None,
                "avg_travel_trust": float(r.avg_travel_trust) if r.avg_travel_trust is not None else None,
                "avg_customer_trust": float(r.avg_customer_trust) if r.avg_customer_trust is not None else None,
                "trusted_order_count": r.trusted_order_count or 0,
                "tap_discipline": float(r.tap_discipline) if r.tap_discipline is not None else None,
                "shadow_mode": bool(r.shadow_mode) if r.shadow_mode is not None else True,
            }
            for r in rows
        ]

    @staticmethod
    async def prediction_recent_orders(db: AsyncSession, limit: int = 50) -> list[dict]:
        """Recent orders that have an event stream — the list an admin drills
        into for FR-A1 timelines."""
        limit = max(1, min(limit, 200))
        rows = (await db.execute(text("""
            SELECT co.id, co.status, co.outlet_id, o.location_name AS outlet_name,
                   t.risk_level, t.travel_source, t.degraded,
                   oo.interval_score, oo.promise_kept,
                   (SELECT count(*) FROM order_events e WHERE e.order_id = co.id) AS event_count,
                   co.created_at
            FROM customer_orders co
            LEFT JOIN outlets o        ON o.id = co.outlet_id
            LEFT JOIN order_twin t     ON t.order_id = co.id
            LEFT JOIN order_outcome oo ON oo.order_id = co.id
            WHERE EXISTS (SELECT 1 FROM order_events e WHERE e.order_id = co.id)
            ORDER BY co.created_at DESC
            LIMIT :lim
        """), {"lim": limit})).fetchall()
        return [
            {
                "order_id": r.id,
                "status": r.status,
                "outlet_id": r.outlet_id,
                "outlet_name": r.outlet_name,
                "risk_level": r.risk_level,
                "travel_source": r.travel_source,
                "degraded": bool(r.degraded) if r.degraded is not None else None,
                "interval_score": float(r.interval_score) if r.interval_score is not None else None,
                "promise_kept": r.promise_kept,
                "event_count": r.event_count or 0,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    async def order_timeline(db: AsyncSession, order_id: uuid.UUID) -> dict:
        """FR-A1 — the full evidence for one order: raw event stream, the twin's
        promise/shadow range, every prediction_log entry, and the scored outcome."""
        head = (await db.execute(text("""
            SELECT co.id, co.status, co.outlet_id, o.location_name AS outlet_name,
                   co.total_amount, co.created_at
            FROM customer_orders co
            LEFT JOIN outlets o ON o.id = co.outlet_id
            WHERE co.id = :o
        """), {"o": str(order_id)})).first()
        if not head:
            raise HTTPException(status_code=404, detail="Order not found")

        events = (await db.execute(text("""
            SELECT seq, event_type, actor_type, source, occurred_at, payload
            FROM order_events WHERE order_id = :o ORDER BY seq
        """), {"o": str(order_id)})).fetchall()

        twin = (await db.execute(text("""
            SELECT promise_start, promise_end, risk_level, travel_source, degraded,
                   ready_sigma_s, hold_tolerance_s, inputs, last_recomputed_at
            FROM order_twin WHERE order_id = :o
        """), {"o": str(order_id)})).first()

        preds = (await db.execute(text("""
            SELECT predictor, model_version, mu_seconds, sigma_seconds, output, predicted_at
            FROM prediction_log WHERE order_id = :o ORDER BY predicted_at, id
        """), {"o": str(order_id)})).fetchall()

        outcome = (await db.execute(text("""
            SELECT actual_prep_s, actual_travel_s, actual_hold_s, counter_wait_s,
                   promise_kept, interval_score, wait_feedback,
                   kitchen_trust, travel_trust, customer_trust, trust_failures
            FROM order_outcome WHERE order_id = :o
        """), {"o": str(order_id)})).first()

        twin_out = None
        if twin:
            inp = twin.inputs if isinstance(twin.inputs, dict) else json.loads(twin.inputs)
            sr = inp.get("shadow_range_min")
            twin_out = {
                "promise_start": twin.promise_start,
                "promise_end": twin.promise_end,
                "shadow_range_min": sr,
                "risk_level": twin.risk_level,
                "travel_source": twin.travel_source,
                "degraded": bool(twin.degraded) if twin.degraded is not None else None,
                "ready_sigma_s": twin.ready_sigma_s,
                "hold_tolerance_s": twin.hold_tolerance_s,
                "last_recomputed_at": twin.last_recomputed_at,
            }

        outcome_out = None
        if outcome:
            outcome_out = {
                "actual_prep_s": outcome.actual_prep_s,
                "actual_travel_s": outcome.actual_travel_s,
                "actual_hold_s": outcome.actual_hold_s,
                "counter_wait_s": outcome.counter_wait_s,
                "promise_kept": outcome.promise_kept,
                "interval_score": float(outcome.interval_score) if outcome.interval_score is not None else None,
                "wait_feedback": outcome.wait_feedback,
                "kitchen_trust": float(outcome.kitchen_trust),
                "travel_trust": float(outcome.travel_trust),
                "customer_trust": float(outcome.customer_trust),
                "trust_failures": outcome.trust_failures,
            }

        return {
            "order_id": head.id,
            "status": head.status,
            "outlet_id": head.outlet_id,
            "outlet_name": head.outlet_name,
            "total_amount": float(head.total_amount) if head.total_amount is not None else 0.0,
            "created_at": head.created_at,
            "events": [
                {
                    "seq": e.seq,
                    "event_type": e.event_type,
                    "actor_type": e.actor_type,
                    "source": e.source,
                    "occurred_at": e.occurred_at,
                    "payload": e.payload,
                }
                for e in events
            ],
            "twin": twin_out,
            "predictions": [
                {
                    "predictor": p.predictor,
                    "model_version": p.model_version,
                    "mu_seconds": p.mu_seconds,
                    "sigma_seconds": p.sigma_seconds,
                    "output": p.output,
                    "predicted_at": p.predicted_at,
                }
                for p in preds
            ],
            "outcome": outcome_out,
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

    # ------------------------- cities (migration 013) -----------------------
    # New-city requests reuse the outlet-verification pattern rather than
    # introducing a second queue: a pending row, an admin decision, and one
    # admin_audit_logs entry written in the SAME transaction as the change.
    @staticmethod
    async def list_cities(
        db: AsyncSession, status_filter: Optional[str] = None
    ) -> list[dict]:
        """All cities, optionally filtered. Pending first — that is the work queue."""
        if status_filter is not None and status_filter not in ("active", "pending", "rejected"):
            raise HTTPException(
                status_code=422,
                detail="Invalid status. Must be one of: ['active', 'pending', 'rejected']",
            )
        rows = (await db.execute(text("""
            SELECT c.id, c.name, c.status, c.created_at, c.decided_at,
                   c.requested_by_outlet_id,
                   o.location_name AS requested_by_outlet_name
            FROM cities c
            LEFT JOIN outlets o ON o.id = c.requested_by_outlet_id
            WHERE (CAST(:status AS varchar) IS NULL
                   OR c.status = CAST(:status AS varchar))
            ORDER BY
                CASE c.status WHEN 'pending' THEN 0 ELSE 1 END,
                c.name
        """), {"status": status_filter})).fetchall()
        return [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "created_at": r.created_at,
                "decided_at": r.decided_at,
                "requested_by_outlet_id": r.requested_by_outlet_id,
                "requested_by_outlet_name": r.requested_by_outlet_name,
            }
            for r in rows
        ]

    @staticmethod
    async def decide_city(
        db: AsyncSession, actor: User, city_id: uuid.UUID, target_status: str
    ) -> dict:
        """Approve (-> active) or reject a requested city.

        Approving makes the name selectable for every FUTURE signup. It does not
        touch `outlets.city` on the requesting outlet: that row already carries
        the name, and rewriting outlet data from an admin decision would be a
        surprising side effect of what reads as a list edit.
        """
        if target_status not in ("active", "rejected"):
            raise HTTPException(
                status_code=422, detail="target_status must be 'active' or 'rejected'"
            )

        current = (await db.execute(text(
            "SELECT id, name, status FROM cities WHERE id = :cid"
        ), {"cid": str(city_id)})).first()
        if not current:
            raise HTTPException(status_code=404, detail="City not found")
        if current.status == target_status:
            raise HTTPException(
                status_code=409, detail=f"City is already '{target_status}'"
            )

        row = (await db.execute(text("""
            UPDATE cities SET status = :s, decided_at = now()
            WHERE id = :cid
            RETURNING id, name, status, decided_at
        """), {"s": target_status, "cid": str(city_id)})).first()

        await AdminService._audit(
            db, actor,
            action=("city.approve" if target_status == "active" else "city.reject"),
            target_type="city", target_id=city_id,
            detail={"name": current.name, "from": current.status, "to": target_status},
        )
        await db.commit()
        return {
            "id": row[0], "name": row[1], "status": row[2], "decided_at": row[3],
        }
