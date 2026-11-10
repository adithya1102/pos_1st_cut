"""TASK 4 — idempotent payment-event log + effect application.

Unit/DB-level tests against app.modules.carevo_payments.reconciliation
directly (no HTTP route exists yet — that is Task 5). Orders are inserted
by raw SQL here rather than through the full checkout flow, to control
status/payment_status/total_amount precisely for each scenario.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_payments import reconciliation as rec
from app.modules.carevo_payments.adapters import VerifiedEvent


async def _insert_order(db, *, outlet_id, customer_id, total_amount=100.0,
                         status="CREATED", payment_status="PENDING") -> str:
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


async def _order_row(db, order_id) -> dict:
    row = (await db.execute(text("""
        SELECT status, payment_status, refund_required, refund_reason,
               vendor_payment_confirmed_at, vendor_payment_confirmed_amount_paise
          FROM customer_orders WHERE id = :id
    """), {"id": str(order_id)})).first()
    return {
        "status": row[0], "payment_status": row[1], "refund_required": row[2],
        "refund_reason": row[3], "vendor_payment_confirmed_at": row[4],
        "vendor_payment_confirmed_amount_paise": row[5],
    }


def _paid_event(order_id, *, event_id, amount_paise=10000, provider="cashfree") -> VerifiedEvent:
    return VerifiedEvent(
        provider=provider, event_id=event_id, order_ref=order_id,
        provider_payment_id=f"pay_{event_id}", amount_paise=amount_paise,
        currency="INR", status="PAID", occurred_at=time.time(), raw={},
    )


class TestSequentialDuplicate:
    @pytest.mark.asyncio
    async def test_second_delivery_of_the_same_event_is_duplicate(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event = _paid_event(order_id, event_id="evt-seq-dup")

        first = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=rec.sha256_hex(b"body-1"))
        assert first["outcome"] == rec.OUTCOME_APPLIED

        second = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=rec.sha256_hex(b"body-1"))
        assert second["outcome"] == rec.OUTCOME_DUPLICATE

        count = await db.scalar(text(
            "SELECT count(*) FROM payment_events WHERE provider='cashfree' AND event_id='evt-seq-dup'"))
        assert count == 1

        row = await _order_row(db, order_id)
        assert row["vendor_payment_confirmed_amount_paise"] == 10000


class TestConcurrentDuplicate:
    @pytest.mark.asyncio
    async def test_two_concurrent_deliveries_produce_one_applied_one_duplicate(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        async def _deliver():
            async with AsyncSessionLocal() as session:
                event = _paid_event(order_id, event_id="evt-concurrent")
                return await rec.apply_vendor_payment_event(
                    session, provider="cashfree", event=event,
                    outlet_id=seed["outlet_id"],
                    body_sha256=rec.sha256_hex(b"concurrent-body"))

        r1, r2 = await asyncio.gather(_deliver(), _deliver())
        outcomes = sorted([r1["outcome"], r2["outcome"]])
        assert outcomes == [rec.OUTCOME_APPLIED, rec.OUTCOME_DUPLICATE]

        count = await db.scalar(text(
            "SELECT count(*) FROM payment_events WHERE provider='cashfree' AND event_id='evt-concurrent'"))
        assert count == 1

        row = await _order_row(db, order_id)
        assert row["vendor_payment_confirmed_amount_paise"] == 10000


class TestAlreadyPaidDifferentEvent:
    @pytest.mark.asyncio
    async def test_a_different_event_for_an_already_paid_order_is_review(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        first = await rec.apply_vendor_payment_event(
            db, provider="cashfree",
            event=_paid_event(order_id, event_id="evt-first"),
            outlet_id=seed["outlet_id"], body_sha256=rec.sha256_hex(b"first"))
        assert first["outcome"] == rec.OUTCOME_APPLIED

        second = await rec.apply_vendor_payment_event(
            db, provider="cashfree",
            event=_paid_event(order_id, event_id="evt-second", amount_paise=10000),
            outlet_id=seed["outlet_id"], body_sha256=rec.sha256_hex(b"second"))
        assert second["outcome"] == rec.OUTCOME_REVIEW
        assert second["reason"] == "already_paid_different_event"

        row = await _order_row(db, order_id)
        # The first (legitimate) confirmation is untouched by the second.
        assert row["vendor_payment_confirmed_amount_paise"] == 10000
        count = await db.scalar(text(
            "SELECT count(*) FROM payment_events WHERE order_id = :id"), {"id": order_id})
        assert count == 2


class TestCrossOutlet:
    @pytest.mark.asyncio
    async def test_payment_for_another_outlets_order_is_review(self, db, seed):
        other_org, other_outlet = uuid.uuid4(), uuid.uuid4()
        await db.execute(text(
            "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
            {"i": str(other_org), "n": "Other Org"})
        await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                                 upi_id, geofence_radius_meters, verification_status,
                                 created_at, cashfree_unlocked)
            VALUES (:i,:o,'Other Outlet','Testville', true, 'other@upi', 150,
                    'active', now(), true)"""),
            {"i": str(other_outlet), "o": str(other_org)})
        await db.commit()

        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree",
            event=_paid_event(order_id, event_id="evt-cross-outlet"),
            outlet_id=other_outlet, body_sha256=rec.sha256_hex(b"cross-outlet"))
        assert result["outcome"] == rec.OUTCOME_REVIEW
        assert result["reason"] == "order_belongs_to_another_outlet"

        row = await _order_row(db, order_id)
        assert row["vendor_payment_confirmed_amount_paise"] is None


class TestAmountMismatch:
    @pytest.mark.asyncio
    async def test_amount_mismatch_is_review(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            total_amount=100.0)

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree",
            event=_paid_event(order_id, event_id="evt-mismatch", amount_paise=9000),
            outlet_id=seed["outlet_id"], body_sha256=rec.sha256_hex(b"mismatch"))
        assert result["outcome"] == rec.OUTCOME_REVIEW
        assert result["reason"] == "amount_mismatch"

        row = await _order_row(db, order_id)
        assert row["vendor_payment_confirmed_amount_paise"] is None


class TestPaymentAfterCancellation:
    @pytest.mark.asyncio
    async def test_payment_after_cancellation_is_review_and_joins_refund_due_queue(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="CANCELLED", payment_status="PENDING")

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree",
            event=_paid_event(order_id, event_id="evt-after-cancel"),
            outlet_id=seed["outlet_id"], body_sha256=rec.sha256_hex(b"after-cancel"))
        assert result["outcome"] == rec.OUTCOME_REVIEW
        assert result["reason"] == "payment_after_cancellation"

        row = await _order_row(db, order_id)
        assert row["refund_required"] is True
        assert row["refund_reason"] == "vendor_payment_after_cancellation"
        assert row["vendor_payment_confirmed_amount_paise"] is None

        queue = await AdminService.list_refund_due(db, limit=500)
        assert any(str(r["order_id"]) == order_id for r in queue)
