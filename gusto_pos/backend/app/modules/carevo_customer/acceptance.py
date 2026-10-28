"""Manual order acceptance (migration 032).

A restaurant whose outlet is in `acceptance_mode='manual'` must TAP Accept on a
paid order within `acceptance_timeout_s`, or the order is cancelled and a refund
is flagged. In `'auto'` — the default, and every outlet until someone opts in —
nothing in this module runs at all and the existing flow is untouched.

WHY THIS IS A SEPARATE FILE
---------------------------
service.py is already ~3,800 lines, and this is a self-contained state machine
with a clear seam: four entry points from the existing flow (payment, scheduled
release, reject, and the deadline sweep) and nothing else. Keeping it apart also
makes the auto-mode guarantee legible — `is_manual()` returning False is the
single gate, and you can read every caller of it on one screen.

THE CONCURRENCY RULE
--------------------
Every transition out of AWAITING is a COMPARE-AND-SET:

    UPDATE customer_orders SET acceptance_state = :new
     WHERE id = :id AND acceptance_state = 'AWAITING'

Postgres serialises the row write, so of N racing actors exactly one gets
rowcount 1 and the rest get 0. That is what makes accept-vs-expire,
accept-vs-reject and two-devices-tapping-Accept all resolve to one winner
without a lock, an advisory lock, or SERIALIZABLE. Nothing in this module
decides a transition by reading the state first and then writing it.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.prediction import events as pe

logger = logging.getLogger(__name__)

AWAITING = "AWAITING"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"

#: Alerts per order, including the first. The ladder stops here even if the
#: deadline has not arrived — three unanswered buzzes is already a restaurant
#: that is not looking at the tablet, and a fourth only trains them to ignore it.
MAX_ALERTS = 3
#: Gap between rungs.
ALERT_INTERVAL_S = 30
#: Consecutive expiries before the outlet is auto-closed.
EXPIRY_CLOSE_THRESHOLD = 3

#: Statuses an acceptance expiry must NEVER cancel (migration 034).
#:
#: The deadline answers "did anybody agree to make this". Once the food IS
#: being made that question is moot, and cancelling it would destroy work in
#: progress — and, for a pay-at-pickup order, strand a customer who is already
#: walking over. The CAS in _expire_one excludes these, and the sweep below
#: skips them so a protected row is not re-examined on every poll forever.
#:
#: Both layers matter: the CAS is the thing that cannot be bypassed, the sweep
#: filter is what stops it being hit.
_EXPIRY_PROTECTED_STATUSES = ("PREPARING", "READY")


def _utcnow() -> datetime:
    """AWARE UTC, matching model._utcnow.

    Every column written here is timestamptz. A naive datetime would be
    localised by the asyncpg dialect using the CLIENT machine's timezone before
    binding, which on an IST box silently shifts every deadline by 5h30m — and
    a deadline that is wrong by hours is the difference between "expired" and
    "still waiting".
    """
    return datetime.now(timezone.utc)


class AcceptanceService:
    # ------------------------------ config --------------------------------
    @staticmethod
    async def outlet_config(db: AsyncSession, outlet_id) -> tuple[str, int]:
        """(mode, timeout_s) for one outlet. Missing row => auto.

        Read with raw SQL because these three columns are deliberately NOT
        mapped on the Outlet model — see the migration 032 commit: Outlet maps
        none of its later-migration columns, and mapping them would make this
        code undeployable until 032 had run on prod.
        """
        row = (await db.execute(text("""
            SELECT acceptance_mode, acceptance_timeout_s
              FROM outlets WHERE id = :oid
        """), {"oid": str(outlet_id)})).first()
        if row is None:
            return "auto", 180
        return (row[0] or "auto"), int(row[1] or 180)

    @staticmethod
    async def is_manual(db: AsyncSession, outlet_id) -> bool:
        """THE gate. Everything else in this module is downstream of it."""
        mode, _ = await AcceptanceService.outlet_config(db, outlet_id)
        return mode == "manual"

    @staticmethod
    async def call_window_s(db: AsyncSession, outlet_id) -> int:
        """The pay-at-pickup confirmation window, in seconds (migration 034).

        SEPARATE from acceptance_timeout_s, which is a "tap the tablet" window.
        A phone call is not that: somebody has to pick up a handset, find the
        order and talk to a person, and tuning one of those windows must not
        move the other.

        Missing row => the 034 default, for the same reason outlet_config
        falls back: a config read must not be the thing that breaks an order.

        The DB caps this at 540 (ck_outlets_call_window) because it MUST stay
        below STOCK_HOLD_TTL_SECONDS — a window longer than the stock hold
        hands the units back while the customer is still waiting for the phone
        to ring. See test_call_window_stays_inside_the_stock_hold.
        """
        row = (await db.execute(text("""
            SELECT call_window_s FROM outlets WHERE id = :oid
        """), {"oid": str(outlet_id)})).first()
        if row is None:
            return 300
        return int(row[0] or 300)

    # --------------------------- entering AWAITING -------------------------
    @staticmethod
    async def begin_awaiting(db: AsyncSession, order, *, reason: str) -> datetime:
        """Put a paid order into AWAITING. Runs in the CALLER's transaction.

        Does NOT commit and does NOT push — both are the caller's job, because
        this has to land atomically with the PAID transition (or with the
        scheduled release) and a push must never happen inside a transaction
        that might still roll back.

        Returns the deadline it stamped.

        `reason` ∈ {payment, scheduled_release, pay_at_pickup_placed} and rides
        the ORDER_ALERTED payload, so "did this clock start at payment, at
        release, or at placement" is answerable from the event log alone. For a
        scheduled order the clock MUST start at release — a pickup three hours
        out whose deadline was set at payment would expire before the kitchen
        ever saw it.

        WHICH WINDOW APPLIES depends on the reason, not on the outlet's mode
        (migration 034). 'pay_at_pickup_placed' uses call_window_s, because
        what the restaurant has to do is RING SOMEBODY; every other reason uses
        acceptance_timeout_s, because what it has to do is tap a tablet. Keyed
        off `reason` rather than re-reading payment_mode from the row so there
        is exactly one input deciding it, and it is the one the caller already
        had to be explicit about.
        """
        if reason == "pay_at_pickup_placed":
            timeout_s = await AcceptanceService.call_window_s(db, order.outlet_id)
        else:
            _, timeout_s = await AcceptanceService.outlet_config(db, order.outlet_id)
        now = _utcnow()
        deadline = now + timedelta(seconds=timeout_s)

        await db.execute(text("""
            UPDATE customer_orders
               SET acceptance_state = :st,
                   acceptance_deadline_at = :dl,
                   alert_count = 0,
                   last_alert_at = NULL
             WHERE id = :id
        """), {"st": AWAITING, "dl": deadline, "id": str(order.id)})

        # The durable record of the pending deadline. Reuses
        # auto_advance_schedule (migration 028) with a THIRD kind rather than a
        # new table: that table already means "one order's next step and when
        # it is due" and already survives a redeploy, which is exactly what an
        # acceptance deadline needs. kind='acceptance' is what keeps
        # process_due_auto_advances from treating it as roster automation.
        await db.execute(text("""
            INSERT INTO auto_advance_schedule
                (order_id, next_stage, due_at, kind, updated_at)
            VALUES (:oid, 'ACCEPTANCE', :due, 'acceptance', now())
            ON CONFLICT (order_id)
            DO UPDATE SET next_stage = 'ACCEPTANCE', due_at = EXCLUDED.due_at,
                          kind = 'acceptance', updated_at = now()
        """), {"oid": str(order.id), "due": deadline})

        # ONE ORDER_ALERTED per order, not one per ladder rung. The rungs are a
        # delivery detail living in alert_count/last_alert_at; this event is the
        # fact that the clock started, and a second one would make "time from
        # alert to decision" ambiguous.
        await pe.write_event(
            db, order.id, pe.ORDER_ALERTED,
            actor_type="system", source="system", outlet_id=order.outlet_id,
            payload={"reason": reason, "timeout_s": timeout_s,
                     "deadline_at": deadline.isoformat()},
        )
        return deadline

    @staticmethod
    async def send_first_alert(db: AsyncSession, order) -> None:
        """Rung 1, AFTER the caller has committed. Best-effort.

        A push failure must never affect a payment that already succeeded, so
        everything here is swallowed. The consequence of losing rung 1 is not
        silence: the ladder in process_acceptance_deadlines re-pushes from
        whatever alert_count says, so a failed first attempt is retried 30s
        later by the sweeper.
        """
        try:
            from app.modules.push.service import PushService
            _, timeout_s = await AcceptanceService.outlet_config(db, order.outlet_id)
            await PushService.alert_outlet_order_pending(
                db, order, attempt=1, seconds_left=timeout_s)
            await db.execute(text("""
                UPDATE customer_orders
                   SET alert_count = 1, last_alert_at = now()
                 WHERE id = :id AND acceptance_state = :st
            """), {"id": str(order.id), "st": AWAITING})
            await db.commit()
        except Exception:
            logger.exception("first acceptance alert failed for order %s", order.id)
            try:
                await db.rollback()
            except Exception:
                pass

    # ------------------------------- accept --------------------------------
    @staticmethod
    async def accept(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, prep_minutes: int, actor_user_id=None,
    ) -> dict:
        """Staff accept a pending order. Outlet-scoped, compare-and-set.

        THE EVENTS ARE DELIBERATELY THE SAME AS AUTO MODE.

        A tapped accept writes an EXPLICIT ORDER_ACCEPTED (source='tap', the
        staff actor, and the promised prep_minutes) and then the inferred
        PREP_STARTED exactly as mark_paid does today. The prediction engine
        therefore sees the identical event pair it has always seen, in the
        identical order — only `source` and the actor differ on the first one,
        and both of those are fields it already carries for every other tapped
        event. The ONLY genuinely new data is accepted_at.

        That choice is why manual mode needs no change anywhere in
        prediction/: compute_outcome still derives actual_prep_s as
        (ready_at - prep_started_at), and PREP_STARTED still lands at the
        moment cooking really begins — which under manual acceptance is more
        truthful than before, not less.
        """
        if prep_minutes <= 0:
            raise HTTPException(status_code=422, detail="prep_minutes must be positive")

        # Scoped lookup FIRST, so a cross-outlet id is a 404 before any write
        # is attempted — and 404 rather than 403 for the same reason
        # lookup-pickup does it: "exists but is not yours" is information about
        # another outlet's orders.
        row = (await db.execute(text("""
            SELECT acceptance_state, status, payment_mode, pickup_code,
                   payment_claimed_at
              FROM customer_orders
             WHERE id = :id AND outlet_id = :oid
        """), {"id": str(order_id), "oid": str(outlet_id)})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Order not found for this outlet")
        pay_at_pickup = (row[2] or "") == "PAY_AT_PICKUP"
        upi_manual = (row[2] or "") == "UPI_MANUAL"

        # DIRECT UPI: THE ACCEPT TAP IS THE PAYMENT CONFIRMATION (035).
        #
        # It cannot happen before the customer has claimed to have paid —
        # there would be nothing for staff to have checked. The claim is also
        # what opened this acceptance window in the first place, so reaching
        # here without one means the order is in AWAITING for some other
        # reason, which should not be possible; refused rather than assumed.
        #
        # This is the single most load-bearing tap in the direct-UPI flow:
        # what the staff member is asserting is "I looked at my own UPI app and
        # the exact amount is there". The owner app puts that sentence on the
        # confirm dialog for the same reason.
        if upi_manual and row[4] is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "PAYMENT_NOT_CLAIMED",
                    "message": (
                        "The customer has not said they have paid yet. Wait "
                        "for them, or reject the order."
                    ),
                })

        # COMPARE-AND-SET. This is the race winner-picker: two devices tapping
        # Accept, or an Accept arriving as the sweeper expires the order, all
        # funnel through this one UPDATE and exactly one sees rowcount 1.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET acceptance_state = :new,
                   accepted_at = now(),
                   prep_minutes_committed = :pm
             WHERE id = :id AND acceptance_state = :old
        """), {"new": ACCEPTED, "old": AWAITING, "pm": prep_minutes,
               "id": str(order_id)})
        if res.rowcount != 1:
            await db.rollback()
            current = row[0]
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_awaiting_acceptance",
                    "acceptance_state": current,
                    "message": AcceptanceService._lost_race_message(current),
                },
            )

        await pe.write_event(
            db, order_id, pe.ORDER_ACCEPTED,
            actor_type="staff", source="tap", outlet_id=outlet_id,
            actor_id=actor_user_id,
            payload={"prep_minutes": prep_minutes, "derived_from": "staff_accept"},
        )
        await pe.write_event(
            db, order_id, pe.PREP_STARTED,
            actor_type="system", source="inferred", outlet_id=outlet_id,
            payload={"derived_from": "staff_accept"},
        )
        # The deadline is settled; drop the durable row so the poller stops
        # considering this order.
        await db.execute(text(
            "DELETE FROM auto_advance_schedule WHERE order_id = :id "
            "AND kind = 'acceptance'"), {"id": str(order_id)})
        await AcceptanceService._reset_expiries(db, outlet_id)

        # ------------- PAY AT PICKUP: stock + pickup code (034) -------------
        #
        # Both belong to ACCEPT rather than to placement, and both are in THIS
        # transaction so a half-accepted order is not a state that exists.
        #
        # STOCK. A pay-at-pickup order is never payment_status='PAID' until the
        # handover, and StockService.sweep_expired reclaims any HELD row whose
        # order is not PAID once expires_at passes. Left alone, the hold would
        # lapse ~10 minutes in — WHILE THE FOOD WAS BEING COOKED — and the dish
        # would read as available again to everyone else. Committing here is
        # what takes the reservation out of the sweeper's reach, and it is
        # truthful at exactly this moment: a human has just said they will make
        # it, so the units are genuinely spent.
        #
        # PICKUP CODE. Minted here, not at placement, for two reasons. Codes
        # are unique only among an outlet's LIVE orders, so one issued to an
        # order that is then rejected would have to be reclaimed; and migration
        # 032 already established that a code must not reach the customer
        # before the restaurant has agreed to make the food. The prepaid path
        # is untouched — there the code is still minted by mark_paid.
        # DIRECT UPI: RECORD THE MONEY, IN THIS TRANSACTION (035).
        #
        # One transaction with the ACCEPTED transition and the pickup code, so
        # there is no instant at which the order is accepted but the payment is
        # not recorded (or the reverse). Stock was already COMMITTED at the
        # claim, so there is nothing to do for it here.
        #
        # record_pickup_payment is reused verbatim — the same function the
        # pay-at-pickup counter handover uses. Both are "a human confirmed
        # money arrived outside the gateway", and it deliberately does not
        # touch `status`, which is what lets it be called from two places that
        # move the status differently (RECEIVED here, COMPLETED there).
        if upi_manual:
            from app.modules.carevo_customer.service import CarevoService as _Svc
            from app.modules.carevo_customer.model import CustomerOrder
            from sqlalchemy import select as _select

            order_obj = (await db.execute(
                _select(CustomerOrder).where(CustomerOrder.id == order_id)
            )).scalars().first()
            await _Svc.record_pickup_payment(
                db, order_obj, method="upi", actor_user_id=actor_user_id,
                at_counter=False)

            if not (row[3] or "").strip():
                target = SimpleNamespace(
                    id=order_id, outlet_id=outlet_id, pickup_code=None)
                # sweep=False: _expire_stale_pickups COMMITS, and this is
                # mid-transaction holding the acceptance CAS, the stock
                # write and (for UPI) the payment record. One commit, or
                # an accepted order could end up paid with no code.
                await _Svc._assign_pickup_code(db, target, sweep=False)

        if pay_at_pickup:
            from app.modules.carevo_customer.stock import StockService
            await StockService.commit_for_order(db, order_id)

            if not (row[3] or "").strip():
                from app.modules.carevo_customer.service import CarevoService as _Svc

                # SimpleNamespace, not a local class: _assign_pickup_code reads
                # .id and .outlet_id and writes .pickup_code, and a class body
                # cannot be used here — `outlet_id = outlet_id` in a class body
                # raises NameError, because class bodies skip the enclosing
                # function scope on reads. The ORM object is not loaded on this
                # path (accept is raw SQL throughout) and fetching one just to
                # mint a code would be a wasted query.
                target = SimpleNamespace(
                    id=order_id, outlet_id=outlet_id, pickup_code=None)
                # sweep=False: _expire_stale_pickups COMMITS, and this is
                # mid-transaction holding the acceptance CAS, the stock
                # write and (for UPI) the payment record. One commit, or
                # an accepted order could end up paid with no code.
                await _Svc._assign_pickup_code(db, target, sweep=False)

        await db.commit()

        # PAID -> RECEIVED through the SAME advance_status every other path
        # uses, so the WS broadcast, the customer push and the TTL restart all
        # happen in the one existing place rather than being re-implemented.
        from app.modules.carevo_customer.service import CarevoService
        order = await CarevoService.advance_status(
            db, order_id, "RECEIVED", outlet_id=outlet_id)

        await AcceptanceService._announce_resolved(db, order, outcome="accepted")
        return {
            "order_id": order_id,
            "status": order.status,
            "acceptance_state": ACCEPTED,
            "prep_minutes": prep_minutes,
        }

    @staticmethod
    def _lost_race_message(current: Optional[str]) -> str:
        if current == ACCEPTED:
            return "This order was already accepted."
        if current == REJECTED:
            return "This order was rejected."
        if current == EXPIRED:
            return ("This order expired before it was accepted and the customer "
                    "has been refunded.")
        return "This order is not waiting for acceptance."

    # ------------------------------- reject --------------------------------
    @staticmethod
    async def cas_reject(db: AsyncSession, order_id) -> bool:
        """AWAITING -> REJECTED, in the caller's transaction. No commit.

        Called from CarevoService.reject_order so a manual-mode reject settles
        the acceptance axis in the SAME transaction as the CANCELLED status —
        otherwise the sweeper could expire an order a human had just rejected,
        producing two terminal causes for one order.

        Returns True when this call made the transition. False means the order
        was not AWAITING: either an auto-mode order (acceptance_state NULL),
        which is the overwhelmingly common case and not an error, or a race
        already settled by someone else.
        """
        res = await db.execute(text("""
            UPDATE customer_orders SET acceptance_state = :new
             WHERE id = :id AND acceptance_state = :old
        """), {"new": REJECTED, "old": AWAITING, "id": str(order_id)})
        if res.rowcount == 1:
            await db.execute(text(
                "DELETE FROM auto_advance_schedule WHERE order_id = :id "
                "AND kind = 'acceptance'"), {"id": str(order_id)})
            return True
        return False

    # ----------------------------- acknowledge -----------------------------
    @staticmethod
    async def acknowledge(db: AsyncSession, order_id, outlet_id) -> dict:
        """Record that a device SAW the alert, which stops the re-push ladder.

        Implemented by pinning alert_count to MAX_ALERTS rather than by adding
        an `alert_acked` column. The ladder's only question is "may I push
        again", and alert_count already answers it; a second column would mean
        two sources of truth for one decision and a migration for no new
        information.

        This does NOT accept the order and does NOT stop the deadline — a
        restaurant that has seen the alert and done nothing must still expire,
        or acknowledging would become a way to park orders indefinitely.
        """
        res = await db.execute(text("""
            UPDATE customer_orders
               SET alert_count = :mx, last_alert_at = now()
             WHERE id = :id AND outlet_id = :oid AND acceptance_state = :st
        """), {"mx": MAX_ALERTS, "id": str(order_id), "oid": str(outlet_id),
               "st": AWAITING})
        await db.commit()
        if res.rowcount != 1:
            # Not awaiting (already settled, or not this outlet's order). Not an
            # error: an ack racing the resolution it describes is normal.
            return {"order_id": order_id, "acknowledged": False}
        return {"order_id": order_id, "acknowledged": True}

    # --------------------------- the deadline sweep -------------------------
    @staticmethod
    async def process_acceptance_deadlines(
        db: AsyncSession, *, outlet_id=None, order_id=None
    ) -> dict:
        """Re-push the ladder and expire whatever is past its deadline.

        Driven from TWO places, deliberately:

          * the durable poller, via auto_advance_schedule kind='acceptance', so
            a deadline fires even if nobody is looking at the app;
          * check-on-read on GET /pos/orders, because this deploy has no
            reliable scheduler — Render's free tier sleeps, and a sleeping
            process does not expire anything. Every staff poll therefore also
            advances the clock, which is the same pattern
            _expire_stale_pickups already uses and for the same reason.

        Idempotent and safe to run concurrently from both: every transition is
        a compare-and-set, so a duplicate run changes nothing.

        Scope to one outlet (the staff poll) or one order (a targeted check);
        with neither, the whole AWAITING set is swept, which is what the poller
        wants.
        """
        clauses = ["acceptance_state = :st"]
        params: dict = {"st": AWAITING}
        # Skip the statuses _expire_one is forbidden to cancel. Without this
        # the sweep would re-select such a row on every poll, fail its CAS
        # every time, and log the warning forever. The CAS guard is still the
        # authority — this only stops it being pointlessly re-tested.
        #
        # Note the re-push ladder is skipped for these rows too, which is
        # right: alerting staff to accept an order they are already cooking
        # would be noise about a decision that has effectively been made.
        clauses.append("upper(coalesce(status, '')) <> ALL(:protected)")
        params["protected"] = list(_EXPIRY_PROTECTED_STATUSES)
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)
        if order_id is not None:
            clauses.append("id = :iid")
            params["iid"] = str(order_id)

        rows = (await db.execute(text(f"""
            SELECT id, outlet_id, total_amount, alert_count, last_alert_at,
                   acceptance_deadline_at, status
              FROM customer_orders
             WHERE {' AND '.join(clauses)}
        """), params)).fetchall()

        expired, alerted = 0, 0
        now = _utcnow()
        for r in rows:
            if r.acceptance_deadline_at is not None and r.acceptance_deadline_at <= now:
                if await AcceptanceService._expire_one(db, r):
                    expired += 1
                continue
            if await AcceptanceService._maybe_realert(db, r, now=now):
                alerted += 1

        return {"expired": expired, "alerted": alerted, "considered": len(rows)}

    @staticmethod
    async def _maybe_realert(db: AsyncSession, r, *, now: datetime) -> bool:
        """One rung, if one is due. Returns True if a push was attempted."""
        if (r.alert_count or 0) >= MAX_ALERTS:
            return False
        if r.last_alert_at is not None:
            if (now - r.last_alert_at).total_seconds() < ALERT_INTERVAL_S:
                return False

        attempt = (r.alert_count or 0) + 1
        seconds_left = None
        if r.acceptance_deadline_at is not None:
            seconds_left = int((r.acceptance_deadline_at - now).total_seconds())

        # Increment FIRST, conditionally on the count we read. Two concurrent
        # sweeps (the poller and a staff poll) would otherwise both see
        # alert_count=1 and both push rung 2. The guarded UPDATE makes the
        # increment the race winner-picker, exactly like every other
        # transition here.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET alert_count = :new, last_alert_at = now()
             WHERE id = :id AND acceptance_state = :st AND alert_count = :old
        """), {"new": attempt, "old": r.alert_count or 0, "id": str(r.id),
               "st": AWAITING})
        await db.commit()
        if res.rowcount != 1:
            return False

        try:
            from app.modules.push.service import PushService

            class _OrderShim:
                """alert_outlet_order_pending only reads these four attributes;
                re-fetching the ORM object for a push would be a wasted query."""
                id = r.id
                outlet_id = r.outlet_id
                total_amount = r.total_amount
                status = r.status
                acceptance_state = AWAITING

            await PushService.alert_outlet_order_pending(
                db, _OrderShim(), attempt=attempt, seconds_left=seconds_left)
        except Exception:
            logger.exception("re-alert failed for order %s", r.id)
            try:
                await db.rollback()
            except Exception:
                pass
        return True

    @staticmethod
    async def _expire_one(db: AsyncSession, r) -> bool:
        """Deadline passed with no decision: cancel, flag a refund, tell both sides.

        Compare-and-set on BOTH axes in one statement — acceptance_state must
        still be AWAITING *and* this sets status to CANCELLED together with it.
        An Accept that lands in the same instant takes the row first or loses
        it entirely; there is no window in which an order is both ACCEPTED and
        CANCELLED.
        """
        # refund_required IS CONDITIONAL ON MONEY HAVING MOVED (migration 034).
        #
        # This used to be an unconditional `true`, which was correct while
        # every order reaching here was prepaid: an expired paid order owes the
        # customer their money back. A PAY-AT-PICKUP order that expires owes
        # nothing — nobody ever charged it — and flagging it would put rows
        # into the admin refund queue for money that was never taken, which is
        # worse than useless: it is a worklist of refunds that cannot be paid.
        #
        # Expressed in SQL rather than as a second pass, exactly as
        # _expire_stale_pickups already does it (service.py), so the flag can
        # never disagree with the transition that caused it.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET acceptance_state = :new,
                   status = 'CANCELLED',
                   refund_required = CASE WHEN payment_status = 'PAID'
                                          THEN true ELSE refund_required END,
                   refund_reason = CASE WHEN payment_status = 'PAID'
                                        AND NOT refund_required
                                        THEN :reason ELSE refund_reason END,
                   refund_flagged_at = CASE WHEN payment_status = 'PAID'
                                            AND NOT refund_required
                                            THEN now() ELSE refund_flagged_at END,
                   updated_at = now()
             WHERE id = :id AND acceptance_state = :old
               AND upper(coalesce(status, '')) <> ALL(:protected)
        """), {"new": EXPIRED, "old": AWAITING, "id": str(r.id),
               "reason": "acceptance_expired",
               "protected": list(_EXPIRY_PROTECTED_STATUSES)})
        if res.rowcount != 1:
            await db.rollback()
            # Distinguish the two ways the CAS can miss, because they mean
            # opposite things. Another actor settling the acceptance axis first
            # is the normal race this whole module is built around and is not
            # worth a word. An order sitting in PREPARING/READY while still
            # AWAITING is an INCONSISTENT state that should now be unreachable
            # (advance_status refuses a pay-at-pickup order that is not
            # ACCEPTED), so reaching it means something upstream regressed and
            # it should be loud.
            if (r.status or "").upper() in _EXPIRY_PROTECTED_STATUSES:
                logger.warning(
                    "acceptance expiry REFUSED for order %s: it is %s and "
                    "still AWAITING. The food is being made, so cancelling it "
                    "would be wrong — but this state should be unreachable; "
                    "check what advanced it without an accept.",
                    r.id, r.status)
            return False

        # DIRECT UPI, ALREADY CLAIMED: THE RESTAURANT OWES THE MONEY BACK.
        #
        # The customer said they had sent it and nobody at the restaurant ever
        # looked. By the time the deadline passes the money may well be sitting
        # in their UPI app, so the safe reading — and the only one that is fair
        # to the customer — is that a refund is due.
        #
        # manual_refund_due, never refund_required: CareVo was not in the
        # payment path and cannot reverse it, so it must not enter the gateway
        # refund queue. Set in a separate statement from the CAS above, which
        # has already settled the transition and is what makes this reachable
        # exactly once.
        claimed = await db.scalar(text(
            "SELECT payment_claimed_at FROM customer_orders "
            " WHERE id = :id AND payment_mode = 'UPI_MANUAL'"),
            {"id": str(r.id)})
        if claimed is not None:
            await db.execute(text("""
                UPDATE customer_orders
                   SET manual_refund_due = true,
                       manual_refund_reason = :r
                 WHERE id = :id AND NOT manual_refund_due
            """), {"r": "acceptance_expired_after_payment_claim",
                   "id": str(r.id)})
            await pe.write_event(
                db, r.id, pe.MANUAL_REFUND_DUE,
                actor_type="system", source="system", outlet_id=r.outlet_id,
                payload={"reason": "acceptance_expired_after_payment_claim"},
            )

        await pe.write_event(
            db, r.id, pe.ORDER_EXPIRED,
            actor_type="system", source="system", outlet_id=r.outlet_id,
            payload={"reason": "acceptance_timeout",
                     "deadline_at": r.acceptance_deadline_at.isoformat()
                     if r.acceptance_deadline_at else None,
                     "alerts_sent": r.alert_count or 0},
        )
        await db.execute(text(
            "DELETE FROM auto_advance_schedule WHERE order_id = :id "
            "AND kind = 'acceptance'"), {"id": str(r.id)})
        # STOCK (033): nobody is cooking this, so the units go back. Same
        # transaction as the cancellation, so the two can never diverge.
        from app.modules.carevo_customer.stock import StockService
        await StockService.release_for_order(db, r.id, reason="acceptance_expired")
        await db.commit()

        # The outlet's strike count, and the auto-close at three.
        await AcceptanceService._bump_expiries_and_maybe_close(db, r.outlet_id)

        # Customer: reuse the ONE existing status choke point so the WS banner
        # and the FCM push both fire from where every other transition fires.
        # CANCELLED already has honest customer-facing copy that mentions the
        # refund (push/service.py _ORDER_STATUS_COPY).
        try:
            from app.modules.carevo_customer.service import CarevoService
            from app.modules.carevo_customer.model import CustomerOrder
            from sqlalchemy import select as _select
            order = (await db.execute(
                _select(CustomerOrder).where(CustomerOrder.id == r.id)
            )).scalars().first()
            if order is not None:
                await CarevoService._broadcast_status(order, db)
                await AcceptanceService._announce_resolved(
                    db, order, outcome="expired")
        except Exception:
            logger.exception("expiry notification failed for order %s", r.id)
            try:
                await db.rollback()
            except Exception:
                pass
        return True

    # ---------------------------- outlet strikes ---------------------------
    @staticmethod
    async def _reset_expiries(db: AsyncSession, outlet_id) -> None:
        """Any decision — accept OR reject — clears the strike count.

        The counter is about an outlet that has stopped answering, so a single
        answer of either kind proves it is answering again. Runs in the
        caller's transaction.
        """
        await db.execute(text(
            "UPDATE outlets SET consecutive_expiries = 0 WHERE id = :oid"),
            {"oid": str(outlet_id)})

    @staticmethod
    async def _bump_expiries_and_maybe_close(db: AsyncSession, outlet_id) -> None:
        """+1 strike, and close the outlet at EXPIRY_CLOSE_THRESHOLD.

        Closes by setting the EXISTING is_manually_closed (migration 024)
        rather than adding a second notion of "closed". A restaurant that has
        let three orders in a row expire is not open, whatever its hours say,
        and customers must stop being able to order from it.

        The counter is NOT reset on close. Reopening is a human action, and
        whoever reopens should also be the one to clear the strikes — zeroing
        it here would let an outlet reopen into the same silence and expire
        another three orders.
        """
        row = (await db.execute(text("""
            UPDATE outlets
               SET consecutive_expiries = consecutive_expiries + 1
             WHERE id = :oid
            RETURNING consecutive_expiries, is_manually_closed
        """), {"oid": str(outlet_id)})).first()
        await db.commit()
        if row is None:
            return
        count, already_closed = row[0], row[1]
        if count < EXPIRY_CLOSE_THRESHOLD or already_closed:
            return

        await db.execute(text(
            "UPDATE outlets SET is_manually_closed = true WHERE id = :oid"),
            {"oid": str(outlet_id)})
        # COMMITTED BEFORE the audit write, deliberately.
        #
        # The close is the customer-protecting half: it stops people ordering
        # from a restaurant that is not answering. The audit row is a record OF
        # it. Writing them in one transaction meant a failing audit INSERT
        # aborted the transaction and silently rolled the close back — which is
        # exactly what happened on the first run of
        # test_three_consecutive_expiries_close_the_outlet: the warning below
        # was logged, and the outlet stayed open. A try/except around the
        # INSERT does not help, because in PostgreSQL the failed statement
        # poisons the whole transaction, not just itself.
        await db.commit()

        # An admin-visible record of an automatic, customer-affecting action,
        # in the EXISTING audit_logs table so it shows up in the admin audit
        # view rather than needing a new surface. Columns are
        # (user_id, action, table_name, ref_id) — there is no free-text detail
        # column, so the count goes into the action string.
        try:
            await db.execute(text("""
                INSERT INTO audit_logs (id, action, table_name, ref_id, created_at)
                VALUES (gen_random_uuid(), :action, 'outlets', :oid, now())
            """), {"action": f"OUTLET_AUTO_CLOSED_AFTER_{count}_EXPIRIES",
                   "oid": str(outlet_id)})
            await db.commit()
        except Exception:
            logger.exception("audit row for outlet auto-close failed (%s)", outlet_id)
            try:
                await db.rollback()
            except Exception:
                pass
        logger.warning("outlet %s auto-closed after %s consecutive expiries",
                       outlet_id, count)

    # ------------------------------ fan-out --------------------------------
    @staticmethod
    async def _announce_resolved(db: AsyncSession, order, *, outcome: str) -> None:
        """Tell the OTHER devices to stop ringing. Best-effort."""
        try:
            from app.modules.push.service import PushService
            await PushService.notify_outlet_order_resolved(
                db, order, outcome=outcome)
            await db.commit()
        except Exception:
            logger.exception("order_resolved push failed for order %s",
                             getattr(order, "id", None))
            try:
                await db.rollback()
            except Exception:
                pass
