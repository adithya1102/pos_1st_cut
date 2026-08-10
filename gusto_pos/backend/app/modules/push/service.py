"""Push notifications for CareVo Skip customers (migration 014).

Three kinds, all RULE-BASED — no model, no learning, no personalisation beyond
a stored aggregate:

  ORDER_STATUS     event-driven, fired from the existing status broadcast hook
  REENGAGEMENT     customers with no paid order for > 14 days (the same
                   threshold the admin activity heuristic already uses)
  DISH_SUGGESTION  names the customer's most-ordered dish and usual outlet

## Sending is gated
`settings.PUSH_ENABLED` + a Firebase SERVICE ACCOUNT gate transmission, the same
way `FIREBASE_ENABLED` gates the inbound auth path. Unconfigured, every send is
logged as 'skipped' and nothing leaves the process — the pipeline is fully
exercisable before credentials exist, and turns live with no code change.

## No scheduler
Nothing here schedules itself. The nudge jobs are plain async functions invoked
by an admin endpoint (see controller.py), because this backend runs on a Render
FREE web service that sleeps after ~15 minutes idle — an in-process scheduler
would fire only while the service happened to be awake. Idempotency lives in the
database (push_notifications), not in scheduler state, so an external trigger
firing twice cannot double-notify.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

KIND_ORDER_STATUS = "ORDER_STATUS"
KIND_REENGAGEMENT = "REENGAGEMENT"
KIND_DISH_SUGGESTION = "DISH_SUGGESTION"
# Staff-addressed kinds (migration 017). These target users.fcm_token, not
# customers.fcm_token — see PushService.send_staff.
KIND_STAFF_NEW_ORDER = "STAFF_NEW_ORDER"
KIND_ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"

# Matches ACTIVITY_ACTIVE_MAX_DAYS in carevo_admin.service — the same "gone
# quiet" definition the admin dashboard shows, so the two never disagree about
# who is lapsing.
REENGAGEMENT_AFTER_DAYS = 14
# A customer gets at most one re-engagement nudge per this window, so a repeated
# trigger (or a daily cron) cannot pester them.
REENGAGEMENT_COOLDOWN_DAYS = 30
# Dish suggestions are lighter but still capped.
DISH_SUGGESTION_COOLDOWN_DAYS = 7

# Customer-visible copy per order status. Statuses absent here get NO push:
# CREATED/PENDING are noise (the customer is still holding the phone), and
# ABANDONED is a TTL expiry nobody needs buzzing about.
#
# CANCELLED is the deliberate exception to "don't buzz bad news". It used to be
# silent alongside ABANDONED, which was right while nothing could produce it.
# Now staff can reject a PAID order, and a customer who has been charged and is
# possibly already walking to the restaurant MUST be told immediately — silence
# there is worse than an unwelcome notification.
_ORDER_STATUS_COPY: dict[str, tuple[str, str]] = {
    "PAID": ("Order confirmed", "Payment received — the kitchen is on it."),
    "RECEIVED": ("Order confirmed", "The restaurant has your order."),
    "PREPARING": ("Being prepared", "Your food is being made right now."),
    "READY": ("Ready for pickup", "Your order is ready — come collect it."),
    "COMPLETED": ("Picked up", "Enjoy! Thanks for using CareVo Skip."),
    # Honest and plain: says what happened, and does not promise a refund
    # timeline the app cannot keep (refunds are handled manually, off-app).
    "CANCELLED": (
        "Order cancelled",
        "The restaurant could not take this order. Your refund is being "
        "arranged — contact them if you need it sooner.",
    ),
}

# Cached OAuth token for FCM HTTP v1 (service accounts issue 1-hour tokens).
_token_cache: dict[str, object] = {"value": None, "expires_at": 0.0}


class PushService:
    # ----------------------------- transport ------------------------------
    @staticmethod
    def _configured() -> bool:
        return bool(
            settings.PUSH_ENABLED
            and settings.FCM_SERVICE_ACCOUNT_FILE
            and settings.FIREBASE_PROJECT_ID
        )

    @staticmethod
    async def _access_token() -> Optional[str]:
        """Mint (and cache) an OAuth access token from the service account.

        Imports google-auth lazily so the module stays importable — and every
        other feature keeps working — on a deployment that never installed it.
        """
        now = time.time()
        cached = _token_cache.get("value")
        if cached and float(_token_cache.get("expires_at", 0)) > now + 60:
            return str(cached)

        try:
            from google.oauth2 import service_account  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore
        except ImportError:
            return None

        try:
            creds = service_account.Credentials.from_service_account_file(
                settings.FCM_SERVICE_ACCOUNT_FILE, scopes=[_SCOPE]
            )
            creds.refresh(Request())
        except Exception:
            return None

        _token_cache["value"] = creds.token
        _token_cache["expires_at"] = (
            creds.expiry.replace(tzinfo=timezone.utc).timestamp()
            if creds.expiry else now + 3000
        )
        return creds.token

    @staticmethod
    async def _transmit(token: str, title: str, body: str, data: dict) -> tuple[bool, str]:
        """POST one message to FCM. Returns (ok, detail)."""
        access = await PushService._access_token()
        if not access:
            return False, "no access token (service account unreadable or google-auth missing)"

        url = FCM_ENDPOINT.format(project=settings.FIREBASE_PROJECT_ID)
        payload = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                # Data values must be strings in FCM v1.
                "data": {k: str(v) for k, v in data.items()},
            }
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {access}"},
                    json=payload,
                )
            if r.status_code // 100 == 2:
                return True, "ok"
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as exc:  # network/timeout
            return False, f"{type(exc).__name__}: {exc}"

    # ------------------------------- core ---------------------------------
    @staticmethod
    async def send(
        db: AsyncSession,
        *,
        customer_id,
        kind: str,
        title: str,
        body: str,
        order_id=None,
        data: Optional[dict] = None,
    ) -> dict:
        """Send one push and log it. Never raises — a failed notification must
        not roll back or block whatever business action triggered it.

        Every attempt writes a push_notifications row, including skips, so
        "not configured" and "never attempted" stay distinguishable later.
        """
        row = (await db.execute(text(
            "SELECT fcm_token FROM customers WHERE id = :cid"
        ), {"cid": str(customer_id)})).first()
        token = row[0] if row else None

        if not token:
            status, detail = "skipped", "customer has no fcm_token"
        elif not PushService._configured():
            status, detail = "skipped", "push disabled (PUSH_ENABLED/service account unset)"
        else:
            ok, detail = await PushService._transmit(
                token, title, body, {"kind": kind, "order_id": str(order_id or ""), **(data or {})}
            )
            status = "sent" if ok else "failed"

        try:
            await db.execute(text("""
                INSERT INTO push_notifications
                    (customer_id, kind, title, body, order_id, status, detail)
                VALUES (:cid, :kind, :title, :body, :oid, :status, :detail)
                ON CONFLICT DO NOTHING
            """), {
                "cid": str(customer_id), "kind": kind, "title": title,
                "body": body[:400], "oid": str(order_id) if order_id else None,
                "status": status, "detail": detail[:1000] if detail else None,
            })
        except Exception:
            pass

        return {"status": status, "detail": detail}

    # ------------------------------ staff ---------------------------------
    @staticmethod
    async def send_staff(
        db: AsyncSession,
        *,
        user_id,
        kind: str,
        title: str,
        body: str,
        order_id=None,
        data: Optional[dict] = None,
    ) -> dict:
        """Staff-addressed twin of [send]. Same contract: never raises, always
        logs, distinguishes skipped from failed.

        Separate from `send` rather than a flag on it because the recipient
        table differs (users vs customers) and push_notifications now records
        exactly one of user_id / customer_id — a single function juggling both
        would be one `if` away from logging a staff push against a customer.
        """
        row = (await db.execute(text(
            "SELECT fcm_token FROM users WHERE id = :uid"
        ), {"uid": str(user_id)})).first()
        token = row[0] if row else None

        if not token:
            status, detail = "skipped", "staff user has no fcm_token"
        elif not PushService._configured():
            status, detail = "skipped", "push disabled (PUSH_ENABLED/service account unset)"
        else:
            ok, detail = await PushService._transmit(
                token, title, body,
                {"kind": kind, "order_id": str(order_id or ""), **(data or {})},
            )
            status = "sent" if ok else "failed"

        try:
            await db.execute(text("""
                INSERT INTO push_notifications
                    (user_id, kind, title, body, order_id, status, detail)
                VALUES (:uid, :kind, :title, :body, :oid, :status, :detail)
                ON CONFLICT DO NOTHING
            """), {
                "uid": str(user_id), "kind": kind, "title": title,
                "body": body[:400], "oid": str(order_id) if order_id else None,
                "status": status, "detail": detail[:1000] if detail else None,
            })
        except Exception:
            pass

        return {"status": status, "detail": detail}

    @staticmethod
    async def notify_outlet_new_order(db: AsyncSession, order) -> dict:
        """Buzz EVERY staff device at the outlet when a paid order lands.

        Unconditional by design: this is the only thing standing between "a
        wrong order gets made" and "staff reject it in time". Since there is no
        Accept gate, the order proceeds regardless — the push is what gives
        staff the chance to intervene, not a thing the order waits on.

        Fans out to all staff of the outlet: one outlet can have several logins
        and there is no way to know which phone is in someone's hand.
        """
        outlet_id = getattr(order, "outlet_id", None)
        if not outlet_id:
            return {"sent": 0, "recipients": 0}

        rows = (await db.execute(text("""
            SELECT id FROM users
            WHERE outlet_id = :oid AND fcm_token IS NOT NULL AND is_active = true
        """), {"oid": str(outlet_id)})).fetchall()

        # Idempotency: mark_paid is idempotent and the gateway retries webhooks,
        # so without this a flaky network becomes three buzzes for one order.
        already = (await db.execute(text("""
            SELECT 1 FROM push_notifications
            WHERE order_id = :oid AND kind = :k AND status = 'sent' LIMIT 1
        """), {"oid": str(order.id), "k": KIND_STAFF_NEW_ORDER})).first()
        if already:
            return {"sent": 0, "recipients": len(rows), "skipped": "already notified"}

        amount = float(getattr(order, "total_amount", 0) or 0)
        title = "New paid order"
        body = "₹{:g} — tap to view. Reject it here if you cannot make it.".format(amount)

        sent = 0
        for r in rows:
            res = await PushService.send_staff(
                db, user_id=r[0], kind=KIND_STAFF_NEW_ORDER,
                title=title, body=body, order_id=order.id,
                data={"order_status": getattr(order, "status", "") or ""},
            )
            if res["status"] == "sent":
                sent += 1
        return {"sent": sent, "recipients": len(rows)}

    # -------------------------- order status ------------------------------
    @staticmethod
    async def notify_order_status(db: AsyncSession, order) -> None:
        """Fired from the existing status-broadcast hook — see
        CarevoService._broadcast_status. Reuses that single choke point rather
        than re-deriving which transitions happened.

        Silent for statuses without customer-facing copy, so CREATED/CANCELLED
        never buzz anyone.
        """
        status = (getattr(order, "status", "") or "").upper()
        copy = _ORDER_STATUS_COPY.get(status)
        if not copy or not getattr(order, "customer_id", None):
            return

        title, body = copy
        already = (await db.execute(text("""
            SELECT 1 FROM push_notifications
            WHERE order_id = :oid AND kind = 'ORDER_STATUS'
              AND title = :t AND status = 'sent' LIMIT 1
        """), {"oid": str(order.id), "t": title})).first()
        if already:
            return  # mark_paid is idempotent and may re-broadcast

        await PushService.send(
            db, customer_id=order.customer_id, kind=KIND_ORDER_STATUS,
            title=title, body=body, order_id=order.id,
            data={"order_status": status},
        )

    # ------------------------------ nudges --------------------------------
    @staticmethod
    async def run_reengagement(db: AsyncSession, limit: int = 200) -> dict:
        """One nudge to customers quiet for > REENGAGEMENT_AFTER_DAYS.

        Once-only is enforced by querying push_notifications for a recent
        REENGAGEMENT, not by scheduler bookkeeping — so re-running this (or
        triggering it twice) is safe.
        """
        rows = (await db.execute(text("""
            WITH last_paid AS (
                SELECT customer_id, max(created_at) AS last_order_at
                FROM customer_orders
                WHERE payment_status = 'PAID'
                GROUP BY customer_id
            )
            SELECT c.id, c.name, lp.last_order_at
            FROM customers c
            JOIN last_paid lp ON lp.customer_id = c.id
            WHERE c.fcm_token IS NOT NULL
              AND lp.last_order_at < now() - make_interval(days => :days)
              AND NOT EXISTS (
                    SELECT 1 FROM push_notifications p
                    WHERE p.customer_id = c.id
                      AND p.kind = 'REENGAGEMENT'
                      AND p.created_at > now() - make_interval(days => :cooldown)
              )
            LIMIT :limit
        """), {
            "days": REENGAGEMENT_AFTER_DAYS,
            "cooldown": REENGAGEMENT_COOLDOWN_DAYS,
            "limit": limit,
        })).fetchall()

        sent = 0
        for r in rows:
            who = (r.name or "").strip()
            greeting = f"{who}, we" if who else "We"
            res = await PushService.send(
                db, customer_id=r.id, kind=KIND_REENGAGEMENT,
                title="Been a while!",
                body=f"{greeting}'ve missed you — your favourites are still here.",
            )
            if res["status"] == "sent":
                sent += 1
        await db.commit()
        return {"candidates": len(rows), "sent": sent, "kind": KIND_REENGAGEMENT}

    @staticmethod
    async def run_dish_suggestion(db: AsyncSession, limit: int = 200) -> dict:
        """Nudge naming the customer's most-ordered dish and usual outlet.

        RULE-BASED: 'most ordered by quantity' and 'most visited', both plain
        aggregates over PAID orders. No time-of-day learning, no model, no
        collaborative filtering — the copy just fills in two names.

        Caller decides WHEN to run it (the mission wants evening); this function
        does not look at the clock, so it stays testable at any hour.
        """
        rows = (await db.execute(text("""
            WITH paid AS (
                SELECT id, customer_id, outlet_id FROM customer_orders
                WHERE payment_status = 'PAID'
            ),
            top_dish AS (
                SELECT DISTINCT ON (p.customer_id)
                       p.customer_id, coi.name_snap AS dish, sum(coi.quantity) AS qty
                FROM paid p
                JOIN customer_order_items coi ON coi.customer_order_id = p.id
                WHERE coi.name_snap IS NOT NULL
                GROUP BY p.customer_id, coi.name_snap
                ORDER BY p.customer_id, qty DESC, coi.name_snap
            ),
            top_outlet AS (
                SELECT DISTINCT ON (p.customer_id)
                       p.customer_id, o.location_name AS outlet, count(*) AS visits
                FROM paid p
                LEFT JOIN outlets o ON o.id = p.outlet_id
                GROUP BY p.customer_id, o.location_name
                ORDER BY p.customer_id, visits DESC, o.location_name
            )
            SELECT c.id, td.dish, tou.outlet
            FROM customers c
            JOIN top_dish td ON td.customer_id = c.id
            LEFT JOIN top_outlet tou ON tou.customer_id = c.id
            WHERE c.fcm_token IS NOT NULL
              AND td.dish IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1 FROM push_notifications p
                    WHERE p.customer_id = c.id
                      AND p.kind = 'DISH_SUGGESTION'
                      AND p.created_at > now() - make_interval(days => :cooldown)
              )
            LIMIT :limit
        """), {"cooldown": DISH_SUGGESTION_COOLDOWN_DAYS, "limit": limit})).fetchall()

        sent = 0
        for r in rows:
            where = f" at {r.outlet}" if r.outlet else ""
            res = await PushService.send(
                db, customer_id=r.id, kind=KIND_DISH_SUGGESTION,
                title="Hungry?",
                body=f"Your usual {r.dish}{where} is a tap away.",
                data={"dish": r.dish or "", "outlet": r.outlet or ""},
            )
            if res["status"] == "sent":
                sent += 1
        await db.commit()
        return {"candidates": len(rows), "sent": sent, "kind": KIND_DISH_SUGGESTION}

    # ------------------------------ tokens --------------------------------
    @staticmethod
    async def register_token(db: AsyncSession, customer, token: str) -> dict:
        """Store/refresh the device token for the signed-in customer."""
        cleaned = (token or "").strip()
        if not cleaned:
            raise ValueError("empty token")
        await db.execute(text(
            "UPDATE customers SET fcm_token = :t, fcm_token_updated_at = now() "
            "WHERE id = :cid"
        ), {"t": cleaned[:512], "cid": str(customer.id)})
        await db.commit()
        return {"ok": True, "push_configured": PushService._configured()}

    @staticmethod
    async def clear_token(db: AsyncSession, customer) -> dict:
        """Drop the token on logout so a shared device stops receiving pushes
        for an account that is no longer signed in."""
        await db.execute(text(
            "UPDATE customers SET fcm_token = NULL, fcm_token_updated_at = now() "
            "WHERE id = :cid"
        ), {"cid": str(customer.id)})
        await db.commit()
        return {"ok": True}
