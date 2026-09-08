"""Queries + window/roster logic for the local testing dashboard.

Roster (migration 025) is the single source of truth for BOTH auto-pickup scope
and the compliance list. Nothing here is customer-facing; all of it sits behind
the X-Testing-Key gate.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.carevo_customer.model import CustomerOrder
# _LIVE_STATUSES is imported, not copied. It is the set verify_pickup itself
# tests (`order.status.upper() in _LIVE_STATUSES`), so can_deliver has to be the
# same object or the button and the endpoint could drift apart.
from app.modules.carevo_customer.service import _LIVE_STATUSES, CarevoService

# The compliance day runs 23:00 -> 23:00 in India. Every outlet, customer, and
# the operating-hours gate (migration 024) already reason in IST, so the day
# boundary is IST too — a UTC boundary would roll over at 04:30/05:30 local,
# splitting an evening's testing across two "days".
TESTING_TZ = ZoneInfo("Asia/Kolkata")
WINDOW_BOUNDARY_HOUR = 23

# --- Roster-scoped auto-progression (testing only) --------------------------
# The stages driven after PAID, in order. READY is the last one we drive: it
# triggers the EXISTING auto-pickup hook inside advance_status, which closes the
# order — pickup is never reimplemented here, only allowed to chain.
_AUTO_ADVANCE_STAGES = ("RECEIVED", "PREPARING", "READY")

# Rank for a strictly-forward guard: the worker never moves an order backward
# and never re-animates a finished one. Anything terminal stops the chain.
_STAGE_RANK = {"CREATED": 0, "PAID": 1, "RECEIVED": 2, "PREPARING": 3,
               "READY": 4, "COMPLETED": 5}
_TERMINAL_STATUSES = {"COMPLETED", "CANCELLED", "ABANDONED", "PICKED_UP"}

# --- Manual Approve / Reject decision window (dashboard buttons) -------------
# Approve = advance one stage via CarevoService.advance_status (the exact staff
# action behind /customer/orders/{id}/advance and auto_receive). Offered only
# before the kitchen commits — accepting (PAID -> RECEIVED) or starting prep
# (RECEIVED -> PREPARING). Hidden from PREPARING on: past the accept gate.
#
# CREATED was REMOVED from this set. advance_status maps CREATED straight to
# RECEIVED (`if cur in ("CREATED","PAID")`), so Approve on a CREATED order put
# an order nobody had paid for into the kitchen queue — indistinguishable there
# from a paid one, and it would then be prepared and handed over for free. An
# unpaid order has nothing to approve; payment is what makes it real.
_APPROVABLE_STATUSES = {"PAID", "RECEIVED"}
# Reject = CarevoService.reject_order verbatim. Its real accepted set is
# REJECTABLE_STATUSES = {PAID, RECEIVED, PREPARING} (same set owner_app's Reject
# button uses), so the button mirrors it exactly rather than inventing a stricter
# rule the server would disagree with.
_REJECTABLE_STATUSES = CarevoService.REJECTABLE_STATUSES
# Ready = the SAME advance_status, called with an explicit target of READY —
# the last stage the auto-advance worker drives (_AUTO_ADVANCE_STAGES above), so
# the button is the manual twin of that step and not a new path.
#
# Offered only from PREPARING, which picks up exactly where Approve stops:
# Approve walks CREATED/PAID -> RECEIVED -> PREPARING and is then hidden, so a
# row shows Approve or Ready, never both.
#
# WHY THE GATE IS ENFORCED HERE AND NOT LEFT TO THE SERVER, unlike Approve and
# Reject: those two are self-guarding. Approve calls advance_status with NO
# target, so the real function computes the next stage and physically cannot
# skip one; Reject is refused by reject_order's own REJECTABLE_STATUSES check.
# advance_status with an EXPLICIT target validates only that the target is a
# known stage (`target not in _PROGRESSION` -> 400) and never looks at the
# order's current status — so nothing downstream would stop a stale dashboard
# row from firing Ready at a PAID order and jumping the whole kitchen. The
# check therefore has to live at this call site. It gates, it does not
# re-implement: the transition itself is still advance_status's to perform.
_READYABLE_STATUSES = {"PREPARING"}
# Delivered = CarevoService.verify_pickup with the order's OWN pickup_code —
# byte-for-byte the call maybe_auto_pickup makes, and the same one staff make
# from owner_app. verify_pickup accepts exactly _LIVE_STATUSES (imported above),
# so the button offers itself over exactly that set and nothing wider.
#
# A code is required as well as a live status: verify_pickup compares the
# submitted code against `order.pickup_code`, so an order that has none can
# never verify. Offering the button there would guarantee a failure.
#
# The gate is enforced server-side before the call for a sharper reason than
# tidiness. verify_pickup treats a wrong code OR a non-live status as a FAILED
# ATTEMPT: it increments `failed_attempts` and sets `is_locked` on the third,
# after which the order raises 423 forever. A stale dashboard row firing into
# that would permanently brick a real order, so the state is checked here and
# verify_pickup is only ever called when it can actually succeed.
_DELIVERABLE_STATUSES = _LIVE_STATUSES


def _ist_str(dt: datetime | None) -> str | None:
    """Format a timestamptz as 'YYYY-MM-DD HH:MM' in IST — the project-wide
    Asia/Kolkata convention. asyncpg returns timestamptz as tz-aware (UTC), so
    astimezone is exact."""
    if dt is None:
        return None
    return dt.astimezone(TESTING_TZ).strftime("%Y-%m-%d %H:%M")


def current_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The rolling [23:00 IST, next 23:00 IST) window that contains `now`.

    Returned in UTC, to compare against customer_orders.created_at (stored as
    timestamptz). Clock-injectable so the day-boundary maths is testable.
    """
    now = now or datetime.now(TESTING_TZ)
    ist = now.astimezone(TESTING_TZ)
    boundary = ist.replace(hour=WINDOW_BOUNDARY_HOUR, minute=0, second=0,
                           microsecond=0)
    # At/after 23:00 the new window has already started; before it, we are still
    # inside the window that began at yesterday's 23:00.
    start = boundary if ist >= boundary else boundary - timedelta(days=1)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


class TestingService:
    # ------------------------------ roster --------------------------------
    # The roster keys on `identifier` = COALESCE(phone_number, email) — the SAME
    # convention as contact_labels (026) and the orders view. A phone (OTP)
    # tester and a Google-only (email) tester are matched identically. The
    # phone_number column is kept alongside for display/back-compat: a phone
    # identifier fills it, an email identifier leaves it NULL.
    @staticmethod
    def _norm(value: str) -> str:
        return (value or "").strip()

    @staticmethod
    def _phone_of(identifier: str) -> str | None:
        """The phone_number column value for an identifier: the identifier itself
        when it is a phone, NULL when it is an email (an '@' marks an email)."""
        ident = TestingService._norm(identifier)
        return ident if ident and "@" not in ident else None

    @staticmethod
    async def _customer_identifier(db: AsyncSession, customer_id) -> str | None:
        """A customer's roster identifier: phone when present, else email — the
        exact COALESCE the roster (and labels) key on."""
        return await db.scalar(text(
            "SELECT COALESCE(phone_number, email) FROM customers WHERE id = :cid"
        ), {"cid": str(customer_id)})

    @staticmethod
    async def is_roster_identifier(db: AsyncSession, identifier: str | None) -> bool:
        """True if this phone-or-email identifier is on the roster."""
        if not identifier:
            return False
        return (await db.execute(text(
            "SELECT 1 FROM testers WHERE identifier = :id LIMIT 1"
        ), {"id": TestingService._norm(identifier)})).first() is not None

    @staticmethod
    async def list_testers(db: AsyncSession) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT identifier, phone_number, name, added_at FROM testers "
            "ORDER BY added_at DESC"
        ))).fetchall()
        return [{"identifier": r.identifier, "phone_number": r.phone_number,
                 "name": r.name, "added_at": r.added_at} for r in rows]

    @staticmethod
    async def add_tester(db: AsyncSession, identifier: str, name: str | None) -> dict:
        ident = TestingService._norm(identifier)
        if not ident:
            raise HTTPException(status_code=422, detail="identifier required")
        phone = TestingService._phone_of(ident)
        # Idempotent: re-adding the same identifier just updates the label.
        await db.execute(text("""
            INSERT INTO testers (identifier, phone_number, name)
            VALUES (:id, :ph, :n)
            ON CONFLICT (identifier)
            DO UPDATE SET name = COALESCE(EXCLUDED.name, testers.name),
                          phone_number = EXCLUDED.phone_number
        """), {"id": ident, "ph": phone, "n": (name or "").strip() or None})
        await db.commit()
        row = (await db.execute(text(
            "SELECT identifier, phone_number, name, added_at "
            "FROM testers WHERE identifier = :id"
        ), {"id": ident})).first()
        return {"identifier": row.identifier, "phone_number": row.phone_number,
                "name": row.name, "added_at": row.added_at}

    @staticmethod
    async def remove_tester(db: AsyncSession, identifier: str) -> dict:
        ident = TestingService._norm(identifier)
        res = await db.execute(text(
            "DELETE FROM testers WHERE identifier = :id"), {"id": ident})
        await db.commit()
        return {"removed": res.rowcount or 0, "identifier": ident,
                "phone_number": TestingService._phone_of(ident)}

    # ------------------------------ outlets -------------------------------
    @staticmethod
    async def outlets_status(db: AsyncSession) -> list[dict]:
        rows = (await db.execute(text(
            "SELECT id, location_name, city, is_visible, deactivated_at, "
            "       opens_at, closes_at, is_manually_closed "
            "FROM outlets ORDER BY location_name"
        ))).fetchall()
        out = []
        for r in rows:
            avail = CarevoService.outlet_availability(
                r.opens_at, r.closes_at, bool(r.is_manually_closed))
            out.append({
                "id": r.id,
                "name": r.location_name,
                "city": r.city,
                "is_visible": bool(r.is_visible),
                "is_deactivated": r.deactivated_at is not None,
                "opening_time": r.opens_at.strftime("%H:%M") if r.opens_at else None,
                "closing_time": r.closes_at.strftime("%H:%M") if r.closes_at else None,
                "is_manually_closed": bool(r.is_manually_closed),
                "order_status": avail["status"],
            })
        return out

    # --------------------------- active orders ----------------------------
    @staticmethod
    def resolve_day(day: str | None = None, *, now: datetime | None = None) -> str:
        """The 'YYYY-MM-DD' the order list should show, defaulting to today IST.

        IST, not UTC, and not the browser's clock: the outlets, the operating
        hours and the compliance window all reason in Asia/Kolkata, so "today"
        has to mean the same day here as it does everywhere else in the tool.
        A UTC default would roll the dashboard over to tomorrow at 05:30 local.
        """
        d = (day or "").strip()
        if d:
            # Validated rather than interpolated: this reaches a CAST in SQL,
            # and a parse failure should be a 422 the caller can read, not a
            # database error.
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="day must be YYYY-MM-DD")
            return d
        return (now or datetime.now(TESTING_TZ)).astimezone(
            TESTING_TZ).strftime("%Y-%m-%d")

    @staticmethod
    async def active_orders(db: AsyncSession, day: str | None = None) -> list[dict]:
        """EVERY order across ALL outlets for one IST day, whatever its status.

        Not scoped to one outlet (unlike list_active_orders) and includes the
        customer phone — this is a tester's-eye view, so it deliberately shows
        what the customer-facing and owner-facing APIs never would.

        FLAT and newest-first. The rows used to be regrouped per restaurant by
        the page; they are not any more, so `ORDER BY created_at DESC` is now
        the order the operator actually sees and the newest order is always the
        top row. outlet_name stays in the payload — it became a column instead
        of a heading.

        ## No status filter — this is a DAY view, not a live queue

        It used to exclude COMPLETED/CANCELLED/ABANDONED, so an order vanished
        the moment it finished and a past day showed only whatever was somehow
        still live from it — which for any day older than the 45-minute pickup
        TTL is nothing at all. Worse, an order swept to ABANDONED disappeared
        with no trace on the one surface being watched, which is exactly how a
        run of test orders came to look "lost".

        A day now shows everything that happened on it. Finished orders are not
        noise here; they are the record. The buttons stay correct on their own:
        can_approve/can_ready/can_deliver/can_reject are all computed from
        status sets that contain no terminal status, so a finished row simply
        offers nothing.

        The name is now a slight misnomer — kept because `/testing/orders` and
        every caller already use it, and renaming buys nothing.
        """
        day = TestingService.resolve_day(day)
        rows = (await db.execute(text("""
            SELECT co.id, co.outlet_id, co.status, co.payment_status,
                   co.pickup_code, co.total_amount, co.created_at,
                   o.location_name AS outlet_name,
                   c.phone_number  AS customer_phone,
                   c.name          AS customer_name,
                   -- The identifier the dashboard shows and labels key on:
                   -- phone when the customer has one, else email.
                   COALESCE(c.phone_number, c.email) AS identifier,
                   cl.label        AS label
            FROM customer_orders co
            LEFT JOIN outlets   o ON o.id = co.outlet_id
            LEFT JOIN customers c ON c.id = co.customer_id
            LEFT JOIN contact_labels cl
                   ON cl.identifier = COALESCE(c.phone_number, c.email)
            -- The day IS the whole filter. No status exclusion: see the
            -- docstring — a finished or abandoned order is part of what
            -- happened that day, and hiding it is what made orders look lost.
            --
            -- IST calendar date, matching the created_at_ist column shown in
            -- the row. Comparing in UTC would put an 05:00 IST order on the
            -- previous day.
            WHERE (co.created_at AT TIME ZONE 'Asia/Kolkata')::date
                  = CAST(:day AS date)
            ORDER BY co.created_at DESC
            -- Bound as a real date, not the 'YYYY-MM-DD' string: asyncpg infers
            -- the parameter's type from the CAST and rejects a str outright.
        """), {"day": date.fromisoformat(day)})).fetchall()
        if not rows:
            return []
        ids = [str(r.id) for r in rows]
        items = (await db.execute(text(
            "SELECT customer_order_id, name_snap, quantity "
            "FROM customer_order_items WHERE customer_order_id = ANY(:ids) "
            "ORDER BY created_at"
        ), {"ids": ids})).fetchall()
        by_order: dict = {}
        for it in items:
            by_order.setdefault(str(it.customer_order_id), []).append(
                {"name": it.name_snap, "quantity": it.quantity})
        return [{
            "order_id": r.id,
            "outlet_id": r.outlet_id,
            "outlet_name": r.outlet_name,
            "status": r.status,
            "payment_status": r.payment_status,
            "pickup_code": r.pickup_code,
            "total_amount": float(r.total_amount) if r.total_amount is not None else 0.0,
            "customer_phone": r.customer_phone,
            "customer_name": r.customer_name,
            # Identifier the UI displays + labels key on, and its label (if any).
            "identifier": r.identifier,
            "label": r.label,
            "created_at": r.created_at,
            # Date + time the order was placed, in IST (project convention).
            "created_at_ist": _ist_str(r.created_at),
            # Which manual buttons the dashboard should show for this order —
            # computed server-side so the gate matches what the real endpoints
            # actually accept (see the constants above).
            "can_approve": (r.status or "").upper() in _APPROVABLE_STATUSES,
            "can_reject": (r.status or "").upper() in _REJECTABLE_STATUSES,
            "can_ready": (r.status or "").upper() in _READYABLE_STATUSES,
            # Needs BOTH: verify_pickup matches the submitted code against
            # r.pickup_code, so a live order without one can never verify.
            "can_deliver": ((r.status or "").upper() in _DELIVERABLE_STATUSES
                            and bool(r.pickup_code)),
            "items": by_order.get(str(r.id), []),
        } for r in rows]

    # --------------------- manual approve / ready / reject ----------------
    # All three REUSE the exact staff service functions — no parallel logic. The
    # real functions stay authoritative (advance_status performs the transition;
    # reject_order enforces REJECTABLE_STATUSES and 409s otherwise), so a stale
    # button that fires on a no-longer-valid order is refused rather than
    # silently mis-handled.
    #
    # Where that refusal COMES FROM differs, and only Ready needs help: Approve
    # and Reject are refused by the real functions themselves, while Ready names
    # its target stage explicitly and so is gated by _READYABLE_STATUSES at this
    # call site. See that constant for why.
    @staticmethod
    async def approve_order(db: AsyncSession, order_id) -> dict:
        """Advance an order one stage — the SAME advance_status the owner_app
        progression / auto_receive path calls. Accepts a paid order into the
        kitchen (PAID -> RECEIVED) or starts prep (RECEIVED -> PREPARING)."""
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == order_id))).scalars().first()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        previous = (order.status or "").upper()
        # Hiding the button is not enough on its own. advance_status with no
        # target still maps CREATED -> RECEIVED, so without this the endpoint
        # would happily push an unpaid order into the kitchen for anyone who
        # called it directly or clicked a stale row. Same discipline as
        # ready_order and deliver_order: the flag decides what is SHOWN, this
        # decides what is ALLOWED.
        if previous not in _APPROVABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"An order in {previous} cannot be approved.")
        updated = await CarevoService.advance_status(db, order_id)
        return {"order_id": str(order_id), "previous_status": previous,
                "status": updated.status}

    @staticmethod
    async def ready_order(db: AsyncSession, order_id) -> dict:
        """Mark a prepared order READY — the SAME CarevoService.advance_status,
        given the explicit target the auto-advance worker uses for its final
        stage (_advance_one_scheduled passes 'READY' the same way).

        Nothing about pickup is done here. Reaching READY is what triggers the
        EXISTING auto-pickup hook inside advance_status, so a roster order
        closes itself through the real verify_pickup exactly as it does on the
        automatic path; a non-roster order stops at READY. Both are that hook's
        behaviour, unchanged and not re-stated here.

        409 rather than 400 on a wrong state, matching what reject_order returns
        when it refuses: same meaning (the order moved on), same shape for the
        dashboard's error handling.
        """
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == order_id))).scalars().first()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        previous = (order.status or "").upper()
        if previous not in _READYABLE_STATUSES:
            # See _READYABLE_STATUSES: an explicit target bypasses the ordering
            # advance_status would otherwise impose, so a stale button must be
            # refused here or it would skip stages silently.
            raise HTTPException(
                status_code=409,
                detail=f"Order is {previous}, not PREPARING")
        updated = await CarevoService.advance_status(db, order_id, target="READY")
        return {"order_id": str(order_id), "previous_status": previous,
                "status": updated.status}

    @staticmethod
    async def deliver_order(db: AsyncSession, order_id) -> dict:
        """Hand the order over — the SAME CarevoService.verify_pickup staff call
        from owner_app, given the order's OWN pickup_code.

        Identical in shape to what maybe_auto_pickup already does
        (`verify_pickup(db, order.id, order.pickup_code, order.outlet_id)`), so
        this is the manual twin of auto-pickup rather than a second way to
        complete an order. Passing the order's own code is what makes it a
        verification and not a status write: everything downstream of a real
        counter scan — COMPLETED, PICKUP_VERIFIED, the customer broadcast, the
        prediction outcome — happens because verify_pickup did it.

        Guarded before the call: see _DELIVERABLE_STATUSES. A wrong state there
        would be counted as a failed attempt and could lock the order for good.
        """
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == order_id))).scalars().first()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        previous = (order.status or "").upper()
        if previous not in _DELIVERABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"Order is {previous}, which cannot be handed over")
        if not order.pickup_code:
            raise HTTPException(
                status_code=409, detail="Order has no pickup code yet")
        result = await CarevoService.verify_pickup(
            db, order.id, order.pickup_code, order.outlet_id)
        # verify_pickup's own dict, passed through unaltered — including the
        # {"verified": false, "status": "ABANDONED"} case, where its internal
        # TTL sweep expired the order between the gate above and the call.
        return {"order_id": str(order_id), "previous_status": previous, **result}

    @staticmethod
    async def reject_order(db: AsyncSession, order_id, reason: str | None = None) -> dict:
        """Refuse an order — the SAME CarevoService.reject_order the owner_app
        Reject button calls (-> CANCELLED + ORDER_REJECTED + customer notify).
        The order's own outlet_id is looked up and passed, so the function's
        outlet-scope check is satisfied for this cross-outlet tester tool."""
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == order_id))).scalars().first()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return await CarevoService.reject_order(
            db, order_id, order.outlet_id, reason=reason, actor_user_id=None)

    # ------------------------------ labels --------------------------------
    @staticmethod
    async def set_label(db: AsyncSession, identifier: str, label: str) -> dict:
        """Upsert a human-readable label for an identifier (phone or email).

        An empty/blank label DELETES the tag rather than storing a blank — the
        UI clears a label by sending an empty string.
        """
        ident = (identifier or "").strip()
        if not ident:
            raise HTTPException(status_code=422, detail="identifier required")
        text_label = (label or "").strip()
        if not text_label:
            await db.execute(text(
                "DELETE FROM contact_labels WHERE identifier = :i"), {"i": ident})
            await db.commit()
            return {"identifier": ident, "label": None}
        await db.execute(text("""
            INSERT INTO contact_labels (identifier, label, updated_at)
            VALUES (:i, :l, now())
            ON CONFLICT (identifier)
            DO UPDATE SET label = EXCLUDED.label, updated_at = now()
        """), {"i": ident, "l": text_label})
        await db.commit()
        return {"identifier": ident, "label": text_label}

    # ---------------------------- compliance ------------------------------
    @staticmethod
    async def compliance(db: AsyncSession, now: datetime | None = None) -> dict:
        """For each tester, whether they placed >= 1 order in the current
        rolling 23:00-IST window. 'Placed' = an order row was created, whatever
        its payment/status."""
        start_utc, end_utc = current_window(now)
        # Join on identifier = COALESCE(phone_number, email) so an email-only
        # tester's orders are counted exactly like a phone tester's.
        rows = (await db.execute(text("""
            SELECT t.identifier, t.phone_number, t.name, cl.label,
                   COUNT(co.id) AS order_count
            FROM testers t
            LEFT JOIN contact_labels cl ON cl.identifier = t.identifier
            LEFT JOIN customers c
                   ON COALESCE(c.phone_number, c.email) = t.identifier
            LEFT JOIN customer_orders co
                   ON co.customer_id = c.id
                  AND co.created_at >= :start
                  AND co.created_at <  :end
            GROUP BY t.identifier, t.phone_number, t.name, cl.label
            ORDER BY t.name NULLS LAST, t.identifier
        """), {"start": start_utc, "end": end_utc})).fetchall()
        testers = [{
            "identifier": r.identifier,
            "phone_number": r.phone_number,
            "name": r.name,
            # Label wins for display; falls back to the raw identifier in the UI.
            "label": r.label,
            "order_count": int(r.order_count or 0),
            "ordered": (r.order_count or 0) > 0,
        } for r in rows]
        return {
            "window_start_utc": start_utc,
            "window_end_utc": end_utc,
            "ordered": [t for t in testers if t["ordered"]],
            "not_ordered": [t for t in testers if not t["ordered"]],
        }

    # --------------------------- auto-pickup ------------------------------
    @staticmethod
    async def maybe_auto_pickup(db: AsyncSession, order) -> bool:
        """If `order` is READY and its customer is on the roster (by phone OR
        email), complete it by invoking the SAME internal verify_pickup the staff
        endpoint uses — reused verbatim, never reimplemented. Returns True if
        auto-pickup fired. Best-effort: any failure is swallowed so it can never
        affect the status transition that triggered it.

        Non-roster orders are untouched: the roster check gates everything.
        """
        try:
            if (order.status or "").upper() != "READY":
                return False
            if not order.pickup_code:
                return False
            ident = await TestingService._customer_identifier(db, order.customer_id)
            if not await TestingService.is_roster_identifier(db, ident):
                return False
            # The exact staff pickup logic, with the order's OWN code.
            await CarevoService.verify_pickup(
                db, order.id, order.pickup_code, order.outlet_id)
            return True
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            return False

    # ---------------- auto-progression through the stages -----------------
    # DURABLE by design: the next stage + its due time live in
    # auto_advance_schedule (migration 028), and a background poller
    # (auto_advance_poller_loop) advances due rows. Because the state is in the
    # DB, a backend restart/redeploy resumes any past-due step automatically —
    # nothing is lost the way in-memory asyncio tasks were.
    @staticmethod
    async def maybe_schedule_auto_advance(db: AsyncSession, order) -> bool:
        """When an order reaches PAID, PERSIST the first pending stage (RECEIVED)
        due AUTO_ADVANCE_DELAY_SECONDS from now — but ONLY for a tester's order,
        and ONLY while the feature is switched on. Returns True iff a row was
        written.

        Two gates, both of which leave a REAL customer's order completely alone:
          * the master switch AUTO_ADVANCE_ROSTER_ORDERS is OFF by default — with
            it off nothing is ever scheduled and roster orders stay fully manual;
          * the roster check (by phone OR email, same source of truth as
            auto-pickup) means a non-tester is never scheduled, at any switch value.

        Best-effort by contract: the caller wraps this so a scheduling failure
        can never affect the payment that triggered it.
        """
        if not settings.AUTO_ADVANCE_ROSTER_ORDERS:
            return False
        ident = await TestingService._customer_identifier(db, order.customer_id)
        if not await TestingService.is_roster_identifier(db, ident):
            return False
        due = datetime.now(timezone.utc) + timedelta(
            seconds=settings.AUTO_ADVANCE_DELAY_SECONDS)
        await db.execute(text("""
            INSERT INTO auto_advance_schedule (order_id, next_stage, due_at, updated_at)
            VALUES (:oid, :stage, :due, now())
            ON CONFLICT (order_id)
            DO UPDATE SET next_stage = EXCLUDED.next_stage,
                          due_at = EXCLUDED.due_at, updated_at = now()
        """), {"oid": str(order.id), "stage": _AUTO_ADVANCE_STAGES[0], "due": due})
        await db.commit()
        return True

    @staticmethod
    async def process_due_auto_advances(db: AsyncSession, *, now=None) -> int:
        """Advance every order whose scheduled stage is due. Returns how many
        rows were processed. Called on a loop by the poller and directly by tests.

        The kill switch is honoured HERE too: while AUTO_ADVANCE_ROSTER_ORDERS is
        off, due rows are left untouched (progression pauses) and resume when it
        is turned back on — a durable version of the same switch.
        """
        if not settings.AUTO_ADVANCE_ROSTER_ORDERS:
            return 0
        now = now or datetime.now(timezone.utc)
        due = (await db.execute(text(
            "SELECT order_id, next_stage FROM auto_advance_schedule "
            "WHERE due_at <= :now ORDER BY due_at LIMIT 100"
        ), {"now": now})).fetchall()
        processed = 0
        for r in due:
            try:
                await TestingService._advance_one_scheduled(db, r.order_id, r.next_stage)
                processed += 1
            except Exception:
                try:
                    await db.rollback()
                except Exception:
                    pass
        return processed

    @staticmethod
    async def _advance_one_scheduled(db: AsyncSession, order_id, stage: str) -> None:
        """Run ONE scheduled stage for an order, then rewrite the schedule row to
        the following stage — or delete it once READY has been driven (READY
        chains into the existing auto-pickup, which closes the order).

        Reuses CarevoService.advance_status verbatim — the SAME function a staff
        tap calls — so there is no parallel status-writing path. A monotonic
        guard never moves an order backward and never re-animates a finished one.
        """
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == order_id))).scalars().first()
        cur = (order.status or "").upper() if order is not None else None
        if order is None or cur in _TERMINAL_STATUSES:
            # Order gone or already finished (auto-pickup / staff) — drop the row.
            await db.execute(text(
                "DELETE FROM auto_advance_schedule WHERE order_id = :o"),
                {"o": str(order_id)})
            await db.commit()
            return

        # Advance unless something already moved it to/past this stage.
        if _STAGE_RANK.get(cur, 0) < _STAGE_RANK[stage]:
            await CarevoService.advance_status(db, order_id, stage)

        idx = _AUTO_ADVANCE_STAGES.index(stage)
        if idx + 1 < len(_AUTO_ADVANCE_STAGES):
            nxt = _AUTO_ADVANCE_STAGES[idx + 1]
            due = datetime.now(timezone.utc) + timedelta(
                seconds=settings.AUTO_ADVANCE_DELAY_SECONDS)
            await db.execute(text(
                "UPDATE auto_advance_schedule SET next_stage = :s, due_at = :d, "
                "updated_at = now() WHERE order_id = :o"),
                {"s": nxt, "d": due, "o": str(order_id)})
        else:
            # READY was the last driven stage; auto-pickup closed the order.
            await db.execute(text(
                "DELETE FROM auto_advance_schedule WHERE order_id = :o"),
                {"o": str(order_id)})
        await db.commit()


async def auto_advance_poller_loop() -> None:
    """Background loop: every AUTO_ADVANCE_POLL_SECONDS, advance any due steps.

    This is the durability mechanism — a lightweight periodic check started at
    app startup (main.py), reusing the codebase's own asyncio + AsyncSessionLocal
    pattern rather than adding a broker/scheduler dependency. On restart it simply
    finds past-due rows in auto_advance_schedule and resumes them, so a redeploy
    mid-progression costs nothing. Each pass is best-effort and fully swallowed —
    one bad pass must never kill the loop — and it runs regardless of the kill
    switch, since process_due_auto_advances itself no-ops while the switch is off.
    """
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await TestingService.process_due_auto_advances(db)
        except Exception:
            pass
        await asyncio.sleep(settings.AUTO_ADVANCE_POLL_SECONDS)
