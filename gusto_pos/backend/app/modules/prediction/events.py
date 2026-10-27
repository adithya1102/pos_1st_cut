"""Event sourcing for the Prediction Engine (design doc §8.1, §9, FR-E1/E2).

`write_event` appends one immutable row to `order_events`. It performs NO commit:
the row is written inside the CALLER's transaction, so if the surrounding state
change rolls back, the event does too, and vice-versa (FR-E1 — exactly one event
row per committed transition, zero orphans). `order_events` is append-only,
enforced at the DB level by a trigger (migration 006, FR-E3).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# --- Event catalogue (§9) --------------------------------------------------
ORDER_CREATED = "ORDER_CREATED"
ORDER_PAID = "ORDER_PAID"
ORDER_ACCEPTED = "ORDER_ACCEPTED"
PROMISE_ISSUED = "PROMISE_ISSUED"
PROMISE_REVISED = "PROMISE_REVISED"
PREP_SCHEDULED = "PREP_SCHEDULED"
PREP_STARTED = "PREP_STARTED"
ITEM_READY = "ITEM_READY"
ORDER_READY = "ORDER_READY"
CUSTOMER_DEPARTED = "CUSTOMER_DEPARTED"
LOCATION_PING = "LOCATION_PING"
CUSTOMER_ARRIVED = "CUSTOMER_ARRIVED"
# The customer's own "I've picked this up" acknowledgment (migration 023).
# NOT the same as PICKUP_VERIFIED, which is STAFF confirming the pickup code and
# is the authoritative completion. This is the customer quietening their own
# screen — actor_type=customer, source=tap — and moves no order status. It
# exists so that ack can survive a reinstall/new device instead of living only
# in on-device storage. Sits BEFORE PICKUP_VERIFIED here only for reading order;
# either can occur without the other.
CUSTOMER_PICKED_UP = "CUSTOMER_PICKED_UP"
PICKUP_VERIFIED = "PICKUP_VERIFIED"
WAIT_FEEDBACK = "WAIT_FEEDBACK"
LOAD_SNAPSHOT = "LOAD_SNAPSHOT"
ORDER_ABANDONED = "ORDER_ABANDONED"
ITEM_UNAVAILABLE = "ITEM_UNAVAILABLE"
# Gateway reported the payment did not succeed (failed, dropped, cancelled).
# Distinct from ORDER_ABANDONED, which means the TTL sweeper expired an unpaid
# order — nobody tried to pay. Here somebody tried and it did not go through.
PAYMENT_FAILED = "PAYMENT_FAILED"
# Staff explicitly refused a PAID order. Distinct from ORDER_ABANDONED (TTL)
# and from PAYMENT_FAILED (gateway): this one is a human decision, and it is
# the only one of the three that obliges a refund.
ORDER_REJECTED = "ORDER_REJECTED"
# Train orders (addendum Item 1): the kitchen has been PUSHED that it is time
# to start this order, computed back from the customer's declared arrival.
#
# Purely a notification. It does NOT set PREP_STARTED and does not move the
# order's status — whether staff act on it is their call, exactly like any
# other push. Distinct from PREP_SCHEDULED, which is Item 2's shadow-mode
# event and is not emitted by this path at all.
KITCHEN_START_NOTIFIED = "KITCHEN_START_NOTIFIED"

# --- manual acceptance (migration 032) --------------------------------------
# The outlet has been ALERTED that a paid order is waiting for a human to
# accept it. Emitted once when the order enters acceptance_state='AWAITING',
# not on each rung of the re-push ladder — the ladder is a delivery detail and
# lives in alert_count/last_alert_at, whereas this is the fact that the clock
# started. A second ORDER_ALERTED for one order would make "time from alert to
# decision" ambiguous.
#
# Purely a notification, like KITCHEN_START_NOTIFIED: it does not move the
# status and does not imply acceptance.
ORDER_ALERTED = "ORDER_ALERTED"

# Nobody tapped Accept before acceptance_deadline_at, so the order was
# cancelled by the system.
#
# A FOURTH distinct terminal cause, and the distinctions matter because they
# answer different questions about the same final status:
#   ORDER_ABANDONED  — the TTL sweeper expired it (pickup window elapsed)
#   PAYMENT_FAILED   — the gateway declined
#   ORDER_REJECTED   — a human said no
#   ORDER_EXPIRED    — a human said NOTHING AT ALL
# Only the last two are a restaurant-side failure, and only ORDER_EXPIRED
# counts toward outlets.consecutive_expiries and the auto-close at 3.
ORDER_EXPIRED = "ORDER_EXPIRED"

# An admin recorded that a refund owed on this order has been settled.
#
# NOT a gateway event. Nothing in this repository calls a payment-provider
# refund API; money moves off-app, and this is the audit trail of a human
# saying it happened — hence actor_id is mandatory in practice at the call
# site, so "who cleared this" is always answerable.
ORDER_REFUND_MARKED = "ORDER_REFUND_MARKED"

# --- pay at pickup (migration 034) -------------------------------------------
# No schema change is needed for any of these: order_events.event_type is plain
# TEXT with no CHECK constraint (migration 006), so the catalogue is a code
# convention and adding to it is a code change.
#
# Staff rang the customer to confirm a pay-at-pickup order. Carries the attempt
# number, so "we tried three times" is answerable from the log rather than only
# from the counter on the row.
#
# Purely a record of a human action, like KITCHEN_START_NOTIFIED: it moves no
# status and implies no acceptance. Somebody picking up the phone is not the
# same as somebody agreeing to cook.
ORDER_CALL_PLACED = "ORDER_CALL_PLACED"

# Staff could not reach the customer, so the order was rejected for that
# reason. DISTINCT from a plain ORDER_REJECTED, which is the restaurant
# declining work it could have done: here the restaurant was willing and the
# customer could not be contacted. Both are written on this path — the reject
# for the state change, this one for the cause — because the cause is what
# decides whether the customer or the outlet should be asked to change
# something.
ORDER_CALL_UNREACHABLE = "ORDER_CALL_UNREACHABLE"

# Money changed hands at the counter for a pay-at-pickup order.
#
# Distinct from ORDER_PAID, which this path ALSO writes so that every existing
# reader of "when was this order paid" keeps working unchanged. This one adds
# what ORDER_PAID cannot carry: that it was collected in person, by which
# method, and by which staff member.
PAYMENT_COLLECTED = "PAYMENT_COLLECTED"

# A pay-at-pickup order the customer never came for.
#
# A FIFTH terminal cause, and it is not any of the four above: the food was
# made (so it is not ORDER_REJECTED or ORDER_EXPIRED), no gateway was involved
# (so not PAYMENT_FAILED), and a human positively declared it rather than a
# sweeper inferring it from a clock (so not ORDER_ABANDONED). It is the only
# one that costs the restaurant real food, which is why it increments
# customers.no_show_count and the others do not.
ORDER_NO_SHOW = "ORDER_NO_SHOW"

# --- direct UPI (migration 035) ----------------------------------------------
# The CUSTOMER asserted they have sent the money to the restaurant's VPA.
#
# An assertion, not a payment, and the distinction is the whole design: nothing
# verifies it until a human reads their own UPI app and taps Accept. ORDER_PAID
# is written at THAT point, not here, so "when was this order paid" keeps
# meaning the same thing it means on every other path.
PAYMENT_CLAIMED = "PAYMENT_CLAIMED"

# The restaurant reported that the claimed money never arrived.
#
# Distinct from ORDER_REJECTED, which is the restaurant declining work it could
# have done. Here it is willing and the payment is absent, so the customer —
# not the outlet — is the party the event is about: it increments
# customers.false_claim_count and nothing else does.
PAYMENT_NOT_RECEIVED = "PAYMENT_NOT_RECEIVED"

# The RESTAURANT owes this customer money directly, UPI to UPI.
#
# Deliberately NOT ORDER_REFUND_MARKED, which is an admin recording that a
# GATEWAY refund has been settled and is read by /admin/orders/refund-due.
# CareVo was never in the path of a direct-UPI payment and cannot refund it, so
# the two must not share an event any more than they share a queue.
MANUAL_REFUND_DUE = "MANUAL_REFUND_DUE"

# actor_type ∈ {customer, staff, system}; source ∈ {tap, geofence, system, inferred}


async def write_event(
    db: AsyncSession,
    order_id,
    event_type: str,
    *,
    actor_type: str,
    source: str,
    outlet_id=None,
    actor_id=None,
    occurred_at: datetime | None = None,
    payload: dict | None = None,
) -> None:
    """Append one order_events row in the caller's transaction. Does NOT commit.

    `occurred_at` = real-world time of the action (defaults to server now);
    `recorded_at` defaults to now() in the DB. `outlet_id` is looked up from the
    order when not supplied. `seq` is the next per-order gap-free sequence; the
    UNIQUE(order_id, seq) constraint guarantees integrity under any race (a
    collision aborts the transaction, taking the state change with it).
    """
    if outlet_id is None:
        outlet_id = (await db.execute(
            text("SELECT outlet_id FROM customer_orders WHERE id = :oid"),
            {"oid": str(order_id)},
        )).scalar()
        if outlet_id is None:
            raise ValueError(f"write_event: order {order_id} has no outlet")

    seq = (await db.execute(
        text("SELECT COALESCE(MAX(seq), 0) + 1 FROM order_events WHERE order_id = :oid"),
        {"oid": str(order_id)},
    )).scalar()

    await db.execute(text("""
        INSERT INTO order_events
            (order_id, outlet_id, seq, event_type, occurred_at,
             actor_type, actor_id, source, payload)
        VALUES
            (:oid, :outlet, :seq, :etype, :occurred,
             :atype, :aid, :src, CAST(:payload AS jsonb))
    """), {
        "oid": str(order_id),
        "outlet": str(outlet_id),
        "seq": seq,
        "etype": event_type,
        "occurred": occurred_at or datetime.now(timezone.utc),
        "atype": actor_type,
        "aid": str(actor_id) if actor_id else None,
        "src": source,
        "payload": json.dumps(payload or {}),
    })
