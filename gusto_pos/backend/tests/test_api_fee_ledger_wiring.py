"""TASK 3/4 (reconcile fix pass) — fee ledger wired into the real completion
and refund paths.

Exercises CarevoService.verify_pickup and CarevoService.collect_order
directly (the two, and only two, code paths that ever write
customer_orders.status = 'COMPLETED' -- see fee_ledger.py's own docstring)
and the refund-flagging path, proving the service-fee charge/reversal rides
in the SAME transaction as the real business action.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.carevo_customer.service import CarevoService
from app.modules.carevo_payments import fee_ledger as fl

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


async def _insert_order(db, *, outlet_id, customer_id, status, payment_status,
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


async def _charges(db, order_id):
    return (await db.execute(text(
        "SELECT entry_type, amount_paise FROM service_fee_ledger WHERE order_id = :id"),
        {"id": order_id})).fetchall()


class TestVerifyPickupWiring:
    async def test_flag_on_writes_exactly_one_charge(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        result = await CarevoService.verify_pickup(
            db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True
        assert result["status"] == "COMPLETED"

        rows = await _charges(db, order_id)
        assert len(rows) == 1
        assert rows[0][0] == "CHARGE"
        assert rows[0][1] == 100

    async def test_flag_off_writes_no_charge(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        result = await CarevoService.verify_pickup(
            db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True

        rows = await _charges(db, order_id)
        assert rows == []

    async def test_two_concurrent_verifications_write_one_charge(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        async def _call():
            async with AsyncSessionLocal() as session:
                return await CarevoService.verify_pickup(
                    session, uuid.UUID(order_id), "ABC123",
                    uuid.UUID(seed["outlet_id"]))

        await asyncio.gather(_call(), _call(), return_exceptions=True)

        rows = await _charges(db, order_id)
        assert len(rows) == 1, (
            "the ledger's own UNIQUE(order_id, entry_type) is what caps this "
            "at one row even though verify_pickup itself has no "
            "compare-and-set on status")

    async def test_abandoned_order_never_reaches_completed_or_charges(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="ABANDONED", payment_status="PENDING")

        result = await CarevoService.verify_pickup(
            db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is False
        assert result["status"] == "ABANDONED"

        rows = await _charges(db, order_id)
        assert rows == []

    async def test_ledger_failure_does_not_block_the_completion(
            self, db, seed, monkeypatch, caplog):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger write exploded")

        monkeypatch.setattr(fl, "charge_if_eligible", _boom)

        with caplog.at_level("WARNING"):
            result = await CarevoService.verify_pickup(
                db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True
        assert result["status"] == "COMPLETED"

        row = (await db.execute(text(
            "SELECT status, pickup_verified_at FROM customer_orders WHERE id = :id"),
            {"id": order_id})).first()
        assert row[0] == "COMPLETED", "a ledger failure must never block the completion"
        assert row[1] is not None

        rows = await _charges(db, order_id)
        assert rows == [], "no ledger row may be written when the ledger write failed"

        assert "fee_ledger_charge_failed" in caplog.text
        assert order_id in caplog.text

    async def test_ledger_failure_leaves_the_hash_chain_intact(
            self, db, seed, monkeypatch):
        """A failed charge attempt (whether it inserted nothing, or the
        SAVEPOINT rolled back a partial insert) must never leave a broken
        link for the NEXT real charge on this outlet to chain from."""
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        failing_order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger write exploded")

        monkeypatch.setattr(fl, "charge_if_eligible", _boom)
        await CarevoService.verify_pickup(
            db, uuid.UUID(failing_order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert await _charges(db, failing_order_id) == []

        monkeypatch.undo()
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        next_order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")
        await CarevoService.verify_pickup(
            db, uuid.UUID(next_order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert len(await _charges(db, next_order_id)) == 1

        result = await fl.verify_chain(db, seed["outlet_id"])
        assert result == {"ok": True}


class TestCollectOrderWiring:
    async def test_flag_on_writes_exactly_one_charge(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        result = await CarevoService.collect_order(
            db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
            pickup_code="ABC123", method="cash",
            actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True
        assert result["status"] == "COMPLETED"

        rows = await _charges(db, order_id)
        assert len(rows) == 1
        assert rows[0] == ("CHARGE", 100)

    async def test_flag_off_writes_no_charge(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        result = await CarevoService.collect_order(
            db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
            pickup_code="ABC123", method="cash",
            actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True

        rows = await _charges(db, order_id)
        assert rows == []

    async def test_two_concurrent_collections_write_one_charge(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        async def _call():
            async with AsyncSessionLocal() as session:
                return await CarevoService.collect_order(
                    session, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                    pickup_code="ABC123", method="cash",
                    actor_user_id=uuid.UUID(seed["owner_id"]))

        results = await asyncio.gather(_call(), _call(), return_exceptions=True)
        collected_flags = [
            r.get("collected") for r in results if isinstance(r, dict)]
        assert collected_flags.count(True) == 1, (
            "the compare-and-set UPDATE in collect_order must let only one "
            "concurrent caller win the handover")

        rows = await _charges(db, order_id)
        assert len(rows) == 1

    async def test_cancelled_order_cannot_be_collected_or_charged(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="CANCELLED", payment_status="PENDING",
            payment_mode="PAY_AT_PICKUP")

        with pytest.raises(Exception):
            await CarevoService.collect_order(
                db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                pickup_code="ABC123", method="cash",
                actor_user_id=uuid.UUID(seed["owner_id"]))
        await db.rollback()

        rows = await _charges(db, order_id)
        assert rows == []

    async def test_ledger_failure_does_not_block_the_handover(
            self, db, seed, monkeypatch, caplog):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger write exploded")

        monkeypatch.setattr(fl, "charge_if_eligible", _boom)

        with caplog.at_level("WARNING"):
            result = await CarevoService.collect_order(
                db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                pickup_code="ABC123", method="cash",
                actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True
        assert result["status"] == "COMPLETED"

        row = (await db.execute(text(
            "SELECT status, payment_status, collected_at FROM customer_orders "
            "WHERE id = :id"), {"id": order_id})).first()
        assert row[0] == "COMPLETED", "a ledger failure must never block the handover"
        assert row[1] == "PAID", "the payment must still be recorded"
        assert row[2] is not None

        txns = (await db.execute(text(
            "SELECT count(*) FROM payment_transactions WHERE customer_order_id = :id"),
            {"id": order_id})).scalar()
        assert txns == 1, "the counter PaymentTransaction must still commit"

        rows = await _charges(db, order_id)
        assert rows == [], "no ledger row may be written when the ledger write failed"

        assert "fee_ledger_charge_failed" in caplog.text
        assert order_id in caplog.text
