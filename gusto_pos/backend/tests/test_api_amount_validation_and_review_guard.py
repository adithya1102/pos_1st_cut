"""TASK 6 (reconcile fix pass) — amount_paise validation before any UPDATE,
and confirm/reject only on a pending REVIEW payment_events row.
"""
from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from app.modules.carevo_payments import reconciliation as rec
from app.modules.carevo_payments.adapters import VerifiedEvent
from tests.conftest import API

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


def _event(order_id, *, event_id, amount_paise) -> VerifiedEvent:
    return VerifiedEvent(
        provider="cashfree", event_id=event_id, order_ref=order_id,
        provider_payment_id=f"pay_{event_id}", amount_paise=amount_paise,
        currency="INR", status="PAID", occurred_at=time.time(), raw={},
    )


class TestAmountValidation:
    @pytest.mark.parametrize("bad_amount,label", [
        (-100, "negative"),
        (0, "zero"),
        (100.5, "float"),
        (True, "bool"),
        ("10000", "string"),
        (2147483648, "overflow_int32"),
    ])
    async def test_invalid_amount_routes_to_review_amount_invalid(
            self, db, seed, bad_amount, label):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            total_amount=100.0)
        # event_id (and the body hash below) must be unique PER RUN, not just
        # per test: payment_events has UNIQUE(provider, event_id) and is
        # never cleaned up mid-session, so a literal like "evt-negative"
        # collides with the row THIS SAME test left behind the last time the
        # suite ran against this scratch DB without an intervening reset,
        # and apply_vendor_payment_event correctly reports that as DUPLICATE
        # instead of applying this run's logic.
        unique = uuid.uuid4().hex[:8]
        event = _event(order_id, event_id=f"evt-{label}-{unique}", amount_paise=bad_amount)

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=rec.sha256_hex(f"{label}-{unique}".encode()))

        assert result["outcome"] == rec.OUTCOME_REVIEW
        assert result["reason"] == "AMOUNT_INVALID"

        row = await _order_row(db, order_id)
        assert row["vendor_payment_confirmed_amount_paise"] is None, (
            "no UPDATE must have reached customer_orders for an invalid amount")

    async def test_valid_matching_amount_still_applies(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            total_amount=100.0)
        unique = uuid.uuid4().hex[:8]
        event = _event(order_id, event_id=f"evt-valid-{unique}", amount_paise=10000)

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=rec.sha256_hex(f"valid-{unique}".encode()))
        assert result["outcome"] == rec.OUTCOME_APPLIED

    async def test_max_int32_amount_is_accepted_as_valid_magnitude(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            total_amount=21474836.47)
        unique = uuid.uuid4().hex[:8]
        event = _event(order_id, event_id=f"evt-max-{unique}", amount_paise=2147483647)

        result = await rec.apply_vendor_payment_event(
            db, provider="cashfree", event=event, outlet_id=seed["outlet_id"],
            body_sha256=rec.sha256_hex(f"max-{unique}".encode()))
        assert result["outcome"] == rec.OUTCOME_APPLIED


async def _order_row(db, order_id) -> dict:
    row = (await db.execute(text(
        "SELECT vendor_payment_confirmed_amount_paise FROM customer_orders WHERE id = :id"),
        {"id": str(order_id)})).first()
    return {"vendor_payment_confirmed_amount_paise": row[0]}


async def _insert_payment_event(db, *, outlet_id, order_id, outcome, reason,
                                 event_id=None) -> str:
    row = (await db.execute(text("""
        INSERT INTO payment_events
            (provider, event_id, outlet_id, order_id, body_sha256,
             signature_valid, outcome, reason)
        VALUES ('cashfree', :event_id, :outlet_id, :order_id, 'x', true,
                :outcome, :reason)
        RETURNING id
    """), {"event_id": event_id or uuid.uuid4().hex, "outlet_id": str(outlet_id),
           "order_id": order_id, "outcome": outcome, "reason": reason})).first()
    await db.commit()
    return str(row[0])


class TestReviewStateGuard:
    async def test_confirm_on_non_review_outcome_is_409_and_writes_no_audit(
            self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="APPLIED", reason=None)

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/confirm",
            headers=seed["admin_auth"], json={"reason": "not applicable"})
        assert r.status_code == 409

        count = await db.scalar(text(
            "SELECT count(*) FROM admin_audit_logs WHERE target_id = :id"),
            {"id": event_id})
        assert count == 0

    async def test_reject_on_non_review_outcome_is_409_and_writes_no_audit(
            self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="IGNORED", reason="status_failed")

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={"reason": "not applicable"})
        assert r.status_code == 409

        count = await db.scalar(text(
            "SELECT count(*) FROM admin_audit_logs WHERE target_id = :id"),
            {"id": event_id})
        assert count == 0

    async def test_second_confirm_on_an_already_confirmed_review_event_is_409(
            self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="REVIEW", reason="amount_mismatch")

        first = await client.post(
            f"{API}/admin/payment-events/{event_id}/confirm",
            headers=seed["admin_auth"], json={"reason": "verified manually"})
        assert first.status_code == 200

        second = await client.post(
            f"{API}/admin/payment-events/{event_id}/confirm",
            headers=seed["admin_auth"], json={"reason": "verified again"})
        assert second.status_code == 409

        count = await db.scalar(text(
            "SELECT count(*) FROM admin_audit_logs WHERE target_id = :id "
            "AND action = 'payment_event_confirm'"), {"id": event_id})
        assert count == 1

    async def test_reject_after_confirm_on_the_same_event_is_409(
            self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="REVIEW", reason="order_not_found")

        confirm = await client.post(
            f"{API}/admin/payment-events/{event_id}/confirm",
            headers=seed["admin_auth"], json={"reason": "resolved"})
        assert confirm.status_code == 200

        reject = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={"reason": "actually no"})
        assert reject.status_code == 409

    async def test_confirm_on_a_pending_review_event_succeeds(
            self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="REVIEW", reason="order_belongs_to_another_outlet")

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/confirm",
            headers=seed["admin_auth"], json={"reason": "cross-checked"})
        assert r.status_code == 200
        assert r.json()["decision"] == "confirm"

    async def test_reject_without_reason_is_422(self, client, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=order_id,
            outcome="REVIEW", reason="amount_mismatch")

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={})
        assert r.status_code == 422

        r2 = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={"reason": ""})
        assert r2.status_code == 422
