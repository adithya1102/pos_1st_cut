"""TASK 5 (reconcile fix pass) — event_id is never NULL, and only a real
unique-constraint hit on uq_payment_events_provider_event is reported as
DUPLICATE.

Before this fix: a signed delivery with no provider-supplied event id (the
documented Cashfree case -- a FAILED/PENDING webhook with no cf_payment_id)
hit a NOT NULL violation on payment_events.event_id, which the blanket
`except IntegrityError` mislabelled DUPLICATE, with no row ever recorded --
silently dropping the event from the audit trail every single delivery.
"""
from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from app.modules.carevo_payments import reconciliation as rec
from app.modules.carevo_payments.adapters import VerifiedEvent

pytestmark = pytest.mark.asyncio


async def _insert_order(db, *, outlet_id, customer_id, total_amount=100.0,
                         status="RECEIVED", payment_status="PENDING") -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             created_at, updated_at)
        VALUES (:id, :cust, :outlet, :status, :amt, :pstatus, now(), now())
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "status": status, "amt": total_amount, "pstatus": payment_status})
    await db.commit()
    return str(order_id)


def _event(order_id, *, event_id, status="FAILED", provider="cashfree",
           amount_paise=None) -> VerifiedEvent:
    return VerifiedEvent(
        provider=provider, event_id=event_id, order_ref=order_id,
        provider_payment_id=None, amount_paise=amount_paise,
        currency="INR", status=status, occurred_at=time.time(), raw={},
    )


class TestNullEventIdFallback:
    async def test_failed_delivery_with_no_event_id_is_ignored_not_duplicate(
            self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event = _event(order_id, event_id=None, status="FAILED")
        # The body content (not just the event_id) must be unique PER RUN:
        # payment_events has UNIQUE(provider, event_id), the fallback id for
        # a null event_id is "body:{sha256}" (see reconciliation.py), and
        # nothing deletes rows mid-session -- a literal body like this
        # collides with the row THIS SAME test left behind the last time the
        # suite ran against this scratch DB without an intervening reset.
        body_sha = rec.sha256_hex(f"a-failed-cashfree-webhook-body-{uuid.uuid4().hex}".encode())

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=body_sha)

        assert result["outcome"] == rec.OUTCOME_IGNORED
        assert result["reason"] == "status_failed"
        assert result["payment_event_id"] is not None

        row = (await db.execute(text(
            "SELECT event_id, outcome FROM payment_events WHERE id = :id"),
            {"id": result["payment_event_id"]})).first()
        assert row[0] == f"body:{body_sha}"
        assert row[1] == rec.OUTCOME_IGNORED

    async def test_same_body_redelivered_yields_one_row_and_one_duplicate(
            self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        body_sha = rec.sha256_hex(f"same-body-twice-{uuid.uuid4().hex}".encode())

        first = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=_event(order_id, event_id=None),
            outlet_id=seed["outlet_id"], body_sha256=body_sha)
        assert first["outcome"] == rec.OUTCOME_IGNORED

        second = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=_event(order_id, event_id=None),
            outlet_id=seed["outlet_id"], body_sha256=body_sha)
        assert second["outcome"] == rec.OUTCOME_DUPLICATE
        assert second["payment_event_id"] == first["payment_event_id"]

        count = await db.scalar(text(
            "SELECT count(*) FROM payment_events WHERE event_id = :eid"),
            {"eid": f"body:{body_sha}"})
        assert count == 1

    async def test_a_different_column_s_not_null_violation_is_not_swallowed(
            self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event = _event(order_id, event_id="evt-real-not-null-check")

        with pytest.raises(Exception) as excinfo:
            await rec.apply_vendor_payment_event(
                db, provider=None, event=event, outlet_id=seed["outlet_id"],
                body_sha256=rec.sha256_hex(b"whatever"))
        assert "IntegrityError" in type(excinfo.value).__name__ or \
            "NotNull" in str(excinfo.value) or "null value" in str(excinfo.value)
        await db.rollback()

        count = await db.scalar(text(
            "SELECT count(*) FROM payment_events WHERE event_id = 'evt-real-not-null-check'"))
        assert count == 0, "a real NOT NULL violation must not be reported as a recorded row"
