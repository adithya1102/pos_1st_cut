"""TASK 3 (reconcile fix pass 3) -- a REAL database error inside the
SAVEPOINT, not just a Python-level exception.

Every existing ledger-failure test (test_api_fee_ledger_wiring.py,
test_api_fee_reversal_wiring.py) injects a plain `raise RuntimeError(...)`
in place of the fee call. That proves the `except Exception` catches
*something*, but a RuntimeError never touches the connection -- it never
puts the DB session into Postgres's aborted-transaction state the way a
real failed statement does. These tests replace the fee call with a
function that executes a REAL failing statement (a NOT NULL violation on
service_fee_ledger.amount_paise) through the SAME session, inside the
SAME SAVEPOINT the real fee call would have used, so the ROLLBACK TO
SAVEPOINT path is exercised for real -- and then prove the OUTER
transaction still commits cleanly afterwards.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_customer.service import CarevoService
from app.modules.carevo_payments import fee_ledger as fl

pytestmark = pytest.mark.asyncio

_ACTOR = SimpleNamespace(id=uuid.uuid4(), username="test-admin")


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


async def _not_null_violation(db, order_id, outlet_id, *, commit=False):
    """Executes a REAL failing INSERT through the caller's own session --
    amount_paise is NOT NULL, so this raises an IntegrityError from
    Postgres itself, not a Python-level exception."""
    await db.execute(text("""
        INSERT INTO service_fee_ledger
            (outlet_id, order_id, entry_type, amount_paise, billing_period)
        VALUES (:outlet_id, :order_id, 'CHARGE', NULL, '2026-01')
    """), {"outlet_id": str(outlet_id), "order_id": str(order_id)})


async def _charges(db, order_id):
    return (await db.execute(text(
        "SELECT entry_type FROM service_fee_ledger WHERE order_id = :id"),
        {"id": order_id})).fetchall()


async def _insert_pickup_order(db, *, outlet_id, customer_id, status, payment_status,
                                payment_mode="PREPAID", pickup_code="ABC123",
                                total_amount=200.0) -> str:
    order_id = uuid.uuid4()
    contact_phone = "+919900001111" if payment_mode != "PREPAID" else None
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             payment_mode, pickup_code, failed_attempts, is_locked,
             contact_phone, created_at, updated_at)
        VALUES (:id, :cust, :outlet, :status, :amt, :pstatus, :pmode, :code,
                0, false, :phone, now(), now())
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "status": status, "amt": total_amount, "pstatus": payment_status,
           "pmode": payment_mode, "code": pickup_code, "phone": contact_phone})
    await db.commit()
    return str(order_id)


async def _insert_refund_order(db, *, outlet_id, customer_id, refund_required=True,
                                total_amount=200.0) -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             payment_mode, refund_required, created_at, updated_at)
        VALUES (:id, :cust, :outlet, 'COMPLETED', :amt, 'PAID', 'PREPAID',
                :refund, now(), now())
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "amt": total_amount, "refund": refund_required})
    await db.commit()
    return str(order_id)


class TestVerifyPickupRealDbErrorInSavepoint:
    async def test_not_null_violation_is_swallowed_and_completion_still_commits(
            self, db, seed, monkeypatch, caplog):
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        async def _boom(db_, order_id_, **kwargs):
            await _not_null_violation(db_, order_id_, seed["outlet_id"])

        monkeypatch.setattr(fl, "charge_if_eligible", _boom)

        with caplog.at_level("WARNING"):
            result = await CarevoService.verify_pickup(
                db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True
        assert result["status"] == "COMPLETED"
        assert "fee_ledger_charge_failed" in caplog.text

        row = (await db.execute(text(
            "SELECT status FROM customer_orders WHERE id = :id"),
            {"id": order_id})).first()
        assert row[0] == "COMPLETED", (
            "a real DB-level error inside the SAVEPOINT must still let the "
            "outer transaction commit the completion")
        assert await _charges(db, order_id) == [], (
            "the NOT NULL violation must have inserted nothing -- the "
            "SAVEPOINT rollback must have undone it completely")


class TestCollectOrderRealDbErrorInSavepoint:
    async def test_not_null_violation_is_swallowed_and_handover_still_commits(
            self, db, seed, monkeypatch, caplog):
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        async def _boom(db_, order_id_, **kwargs):
            await _not_null_violation(db_, order_id_, seed["outlet_id"])

        monkeypatch.setattr(fl, "charge_if_eligible", _boom)

        with caplog.at_level("WARNING"):
            result = await CarevoService.collect_order(
                db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                pickup_code="ABC123", method="cash",
                actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True
        assert result["status"] == "COMPLETED"
        assert "fee_ledger_charge_failed" in caplog.text

        row = (await db.execute(text(
            "SELECT status, payment_status FROM customer_orders WHERE id = :id"),
            {"id": order_id})).first()
        assert row[0] == "COMPLETED", (
            "a real DB-level error inside the SAVEPOINT must still let the "
            "outer transaction commit the handover")
        assert row[1] == "PAID", "the payment record must still commit too"
        assert await _charges(db, order_id) == [], (
            "the NOT NULL violation must have inserted nothing")


class TestMarkRefundDoneRealDbErrorInSavepoint:
    async def test_not_null_violation_is_swallowed_and_refund_still_commits(
            self, db, seed, monkeypatch, caplog):
        order_id = await _insert_refund_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        # Charge the order first so reverse_if_charged's real work would
        # otherwise have something to reverse -- the injected failure
        # replaces that write entirely.
        await fl.charge_if_eligible(db, order_id)

        async def _boom(db_, order_id_, **kwargs):
            await _not_null_violation(db_, order_id_, seed["outlet_id"])

        monkeypatch.setattr(fl, "reverse_if_charged", _boom)

        with caplog.at_level("WARNING"):
            result = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert result["refund_required"] is False
        assert "fee_ledger_reversal_failed" in caplog.text

        row = (await db.execute(text(
            "SELECT refund_required FROM customer_orders WHERE id = :id"),
            {"id": order_id})).first()
        assert row[0] is False, (
            "a real DB-level error inside the SAVEPOINT must still let the "
            "outer transaction commit the refund-clear")

        rows = await _charges(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE"], (
            "the earlier real CHARGE must survive untouched, and no "
            "REVERSAL row may exist since the NOT NULL violation must "
            "have inserted nothing")
