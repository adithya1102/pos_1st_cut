"""TASK 4 — idempotent payment-event log + effect application.

ADDITIVE. Nothing existing calls this module yet; it is wired up by the
vendor-gateway webhook route (Task 5), which is itself flag-gated and OFF by
default. Depends on migration 039 (payment_events table,
customer_orders.vendor_payment_confirmed_at/_amount_paise).

THE GUARANTEE: for one (provider, event_id), the INSERT into payment_events
happens BEFORE any effect (the customer_orders UPDATE), inside the SAME
database transaction, and the row's UNIQUE(provider, event_id) constraint is
what makes two concurrent deliveries of the identical event produce exactly
one effect. The second delivery's INSERT blocks on Postgres's unique index
until the first commits, then fails with a unique-violation and is answered
DUPLICATE having applied nothing — there is no window in which both commit.

OUTCOMES (payment_events.outcome, migration 039's CHECK constraint):
  APPLIED   — a PAID event, for a live order at the named outlet, with no
              prior confirmation and a matching amount. The effect ran.
  DUPLICATE — the same (provider, event_id) was already recorded. No effect.
  IGNORED   — a verified event whose status is not PAID (FAILED/PENDING/
              UNKNOWN). Recorded for the audit trail; no effect.
  REVIEW    — a verified event this code refuses to apply automatically:
              unresolvable order, cross-outlet order, payment after
              cancellation (also flags the existing refund-due queue), a
              different event for an already-confirmed order, or an amount
              mismatch. A human resolves these (Task 7).
  REJECTED  — reserved for the webhook route's OWN use when signature
              verification itself fails, before a VerifiedEvent exists at
              all. Nothing in this module produces REJECTED.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.carevo_payments.adapters import VerifiedEvent

OUTCOME_APPLIED = "APPLIED"
OUTCOME_DUPLICATE = "DUPLICATE"
OUTCOME_IGNORED = "IGNORED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_REVIEW = "REVIEW"


def sha256_hex(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


@dataclass(frozen=True)
class _OrderRow:
    id: str
    outlet_id: str
    status: str
    payment_status: str
    total_amount: float
    vendor_payment_confirmed_at: Optional[object]


async def _load_order_for_update(db: AsyncSession, order_ref: str) -> Optional[_OrderRow]:
    """Row-locked read via raw SQL — vendor_payment_confirmed_at is
    deliberately unmapped on the ORM model (see migration 039's header), and
    the FOR UPDATE lock is what makes the "already confirmed, different
    event" REVIEW case correct under concurrency: two different event_ids
    for the same order serialize on this lock rather than racing."""
    try:
        row = (await db.execute(text("""
            SELECT id, outlet_id, status, payment_status, total_amount,
                   vendor_payment_confirmed_at
              FROM customer_orders
             WHERE id = :id
             FOR UPDATE
        """), {"id": str(order_ref)})).first()
    except Exception:
        await db.rollback()
        return None
    if row is None:
        return None
    return _OrderRow(
        id=str(row[0]), outlet_id=str(row[1]), status=row[2] or "",
        payment_status=row[3] or "", total_amount=float(row[4] or 0),
        vendor_payment_confirmed_at=row[5],
    )


def _decide(order: Optional[_OrderRow], event: VerifiedEvent,
            outlet_id) -> tuple[str, Optional[str]]:
    """Pure decision function — no I/O, easy to reason about and to test
    indirectly through apply_vendor_payment_event's outcomes."""
    if order is None:
        return OUTCOME_REVIEW, "order_not_found"
    if order.outlet_id != str(outlet_id):
        return OUTCOME_REVIEW, "order_belongs_to_another_outlet"
    if order.status.upper() == "CANCELLED":
        return OUTCOME_REVIEW, "payment_after_cancellation"

    if event.status != "PAID":
        return OUTCOME_IGNORED, f"status_{(event.status or 'unknown').lower()}"

    already_confirmed = (
        order.vendor_payment_confirmed_at is not None
        or order.payment_status.upper() == "PAID"
    )
    if already_confirmed:
        return OUTCOME_REVIEW, "already_paid_different_event"

    if event.amount_paise is not None:
        if not _is_valid_amount_paise(event.amount_paise):
            return OUTCOME_REVIEW, "AMOUNT_INVALID"
        total_paise = int(round(order.total_amount * 100))
        if event.amount_paise != total_paise:
            return OUTCOME_REVIEW, "amount_mismatch"

    return OUTCOME_APPLIED, None


#: Postgres `integer` (customer_orders.vendor_payment_confirmed_amount_paise
#: and service_fee_ledger.amount_paise are both this type) is a signed
#: 32-bit column; this is its max value.
_MAX_INT32 = 2147483647


def _is_valid_amount_paise(amount_paise) -> bool:
    """int (never bool -- bool is a subclass of int), > 0, <= INT32_MAX.
    Checked before ANY UPDATE is reached -- a value that fails this routes
    to REVIEW instead of ever being written to customer_orders or the fee
    ledger, and instead of letting an out-of-range value raise an uncaught
    DataError mid-transaction."""
    if isinstance(amount_paise, bool):
        return False
    if not isinstance(amount_paise, int):
        return False
    if amount_paise <= 0:
        return False
    if amount_paise > _MAX_INT32:
        return False
    return True


async def apply_vendor_payment_event(
    db: AsyncSession, *, provider: str, event: VerifiedEvent,
    outlet_id, body_sha256: str, signature_valid: bool = True,
) -> dict:
    """Record ONE verified vendor-gateway webhook event and, only for a
    freshly-APPLIED PAID event (or a cancellation-REVIEW), apply its effect
    — all inside one transaction. Returns a dict describing what happened;
    never raises for a business-rule REVIEW/IGNORED/DUPLICATE outcome, only
    for a genuine database error.
    """
    order = await _load_order_for_update(db, event.order_ref) if event.order_ref else None
    outcome, reason = _decide(order, event, outlet_id)
    order_id_for_row = order.id if order is not None else None

    # event_id is NOT NULL (migration 039). A provider delivery that carries
    # no payment/event id of its own (a FAILED/PENDING Cashfree webhook with
    # no cf_payment_id is the known case -- see gateway.py's parse_webhook)
    # must still get a stable, deduplicatable key, or the INSERT below hits a
    # NOT-NULL violation instead of the UNIQUE one and the event is lost.
    # "body:" + sha256(raw body) means a byte-identical redelivery still
    # dedupes, exactly like a real event_id would.
    event_id_for_row = event.event_id or f"body:{body_sha256}"

    try:
        res = await db.execute(text("""
            INSERT INTO payment_events
                (provider, event_id, outlet_id, order_id, body_sha256,
                 signature_valid, outcome, reason)
            VALUES (:provider, :event_id, :outlet_id, :order_id, :body_sha256,
                    :signature_valid, :outcome, :reason)
            RETURNING id
        """), {
            "provider": provider,
            "event_id": event_id_for_row,
            "outlet_id": str(outlet_id),
            "order_id": order_id_for_row,
            "body_sha256": body_sha256,
            "signature_valid": signature_valid,
            "outcome": outcome,
            "reason": reason,
        })
        payment_event_id = res.scalar_one()
    except IntegrityError as exc:
        # Only a hit on uq_payment_events_provider_event (Postgres SQLSTATE
        # 23505, unique_violation) means "this exact (provider, event_id)
        # already committed" -- the one case that is genuinely a duplicate
        # delivery, not a bug. Any other integrity error (a NOT NULL or FK
        # violation on some other column, a different constraint entirely)
        # is a real defect and must surface as one, not be silently
        # relabelled DUPLICATE and reported as if the row existed.
        # exc.orig is SQLAlchemy's asyncpg DBAPI wrapper, which forwards
        # sqlstate but NOT constraint_name; the real asyncpg error (with
        # both) is one level further down, linked via __cause__.
        orig = getattr(exc, "orig", None)
        cause = getattr(orig, "__cause__", None)
        sqlstate = getattr(orig, "sqlstate", None) or getattr(cause, "sqlstate", None)
        constraint_name = (
            getattr(orig, "constraint_name", None)
            or getattr(cause, "constraint_name", None)
        )
        if sqlstate != "23505" or constraint_name != "uq_payment_events_provider_event":
            raise
        await db.rollback()
        existing = (await db.execute(text("""
            SELECT id, order_id FROM payment_events
             WHERE provider = :provider AND event_id = :event_id
        """), {"provider": provider, "event_id": event_id_for_row})).first()
        return {
            "outcome": OUTCOME_DUPLICATE,
            "payment_event_id": str(existing[0]) if existing else None,
            "order_id": str(existing[1]) if existing and existing[1] else None,
            "reason": "duplicate_event_id",
        }

    if outcome == OUTCOME_APPLIED:
        await db.execute(text("""
            UPDATE customer_orders
               SET vendor_payment_confirmed_at = now(),
                   vendor_payment_confirmed_amount_paise = :amt
             WHERE id = :id
        """), {"amt": event.amount_paise, "id": order.id})
    elif outcome == OUTCOME_REVIEW and reason == "payment_after_cancellation":
        # Joins the EXISTING refund-due queue (migration 032), the same
        # columns CarevoService.mark_paid's own terminal-order branch and
        # reject_order already write and carevo_admin's
        # GET /admin/orders/refund-due already reads.
        await db.execute(text("""
            UPDATE customer_orders
               SET refund_required = true,
                   refund_reason = 'vendor_payment_after_cancellation',
                   refund_flagged_at = now()
             WHERE id = :id AND NOT refund_required
        """), {"id": order.id})

    await db.commit()
    return {
        "outcome": outcome,
        "payment_event_id": str(payment_event_id),
        "order_id": order_id_for_row,
        "reason": reason,
    }
