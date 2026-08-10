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
