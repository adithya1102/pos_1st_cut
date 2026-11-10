"""TASK 6 — Rs 1 service-fee ledger.

Unit/DB-level tests against app.modules.carevo_payments.fee_ledger and the
migration-041 triggers/functions directly.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.carevo_payments import fee_ledger as fl


@pytest.fixture(autouse=True)
def _fee_ledger_on(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


async def _insert_order(db, *, outlet_id, customer_id, status="COMPLETED",
                         payment_status="PAID", vendor_confirmed=False) -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             created_at, updated_at,
             vendor_payment_confirmed_at, vendor_payment_confirmed_amount_paise)
        VALUES (:id, :cust, :outlet, :status, 100, :pstatus, now(), now(),
                CASE WHEN :vc THEN now() ELSE NULL END,
                CASE WHEN :vc THEN 10000 ELSE NULL END)
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "status": status, "pstatus": payment_status, "vc": vendor_confirmed})
    await db.commit()
    return str(order_id)


async def _ledger_rows(db, order_id):
    return (await db.execute(text(
        "SELECT entry_type, amount_paise, status FROM service_fee_ledger WHERE order_id = :id"),
        {"id": order_id})).fetchall()


class TestChargeOnce:
    @pytest.mark.asyncio
    async def test_charge_once_under_two_concurrent_completions(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        async def _charge():
            async with AsyncSessionLocal() as session:
                return await fl.charge_if_eligible(session, order_id)

        r1, r2 = await asyncio.gather(_charge(), _charge())
        outcomes = sorted([r1["charged"], r2["charged"]])
        assert outcomes == [False, True]

        rows = await _ledger_rows(db, order_id)
        assert len(rows) == 1
        assert rows[0][0] == "CHARGE"
        assert rows[0][1] == 100

    @pytest.mark.asyncio
    async def test_charging_twice_sequentially_is_also_idempotent(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        first = await fl.charge_if_eligible(db, order_id)
        second = await fl.charge_if_eligible(db, order_id)
        assert first["charged"] is True
        assert second["charged"] is False
        assert second["reason"] == "already_charged"
        rows = await _ledger_rows(db, order_id)
        assert len(rows) == 1


class TestVendorConfirmedIsAlsoBillable:
    @pytest.mark.asyncio
    async def test_vendor_confirmed_payment_without_careco_payment_status_is_billable(
        self, db, seed
    ):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            payment_status="PENDING", vendor_confirmed=True)
        result = await fl.charge_if_eligible(db, order_id)
        assert result["charged"] is True


class TestCancelledOrderNotCharged:
    @pytest.mark.asyncio
    async def test_cancelled_order_is_never_charged(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="CANCELLED", payment_status="PAID")
        result = await fl.charge_if_eligible(db, order_id)
        assert result["charged"] is False
        assert result["reason"] == "not_billable"
        rows = await _ledger_rows(db, order_id)
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_abandoned_order_is_never_charged(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="ABANDONED", payment_status="PENDING")
        result = await fl.charge_if_eligible(db, order_id)
        assert result["charged"] is False

    @pytest.mark.asyncio
    async def test_flag_off_writes_nothing(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.charge_if_eligible(db, order_id)
        assert result["charged"] is False
        assert result["reason"] == "flag_off"
        rows = await _ledger_rows(db, order_id)
        assert len(rows) == 0


class TestRefundWritesExactlyOneReversal:
    @pytest.mark.asyncio
    async def test_refund_after_a_charge_writes_one_reversal(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        await fl.charge_if_eligible(db, order_id)

        first = await fl.reverse_if_charged(db, order_id)
        second = await fl.reverse_if_charged(db, order_id)
        assert first["reversed"] is True
        assert second["reversed"] is False
        assert second["reason"] == "already_reversed"

        rows = await _ledger_rows(db, order_id)
        types = sorted(r[0] for r in rows)
        assert types == ["CHARGE", "REVERSAL"]

    @pytest.mark.asyncio
    async def test_reversing_an_uncharged_order_writes_nothing(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.reverse_if_charged(db, order_id)
        assert result["reversed"] is False
        assert result["reason"] == "no_charge_to_reverse"


class TestImmutability:
    @pytest.mark.asyncio
    async def test_direct_update_of_amount_is_rejected(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.charge_if_eligible(db, order_id)
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE service_fee_ledger SET amount_paise = 999 WHERE id = :id"),
                {"id": result["entry_id"]})
        await db.rollback()

    @pytest.mark.asyncio
    async def test_direct_update_of_entry_hash_is_rejected(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.charge_if_eligible(db, order_id)
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE service_fee_ledger SET entry_hash = repeat('0', 64) WHERE id = :id"),
                {"id": result["entry_id"]})
        await db.rollback()

    @pytest.mark.asyncio
    async def test_direct_delete_is_rejected(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.charge_if_eligible(db, order_id)
        with pytest.raises(Exception):
            await db.execute(text(
                "DELETE FROM service_fee_ledger WHERE id = :id"), {"id": result["entry_id"]})
        await db.rollback()

    @pytest.mark.asyncio
    async def test_status_and_invoice_ref_may_change_via_the_one_function(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        result = await fl.charge_if_eligible(db, order_id)
        await fl.advance_status(db, result["entry_id"], "INVOICED", "INV-0001")
        row = (await db.execute(text(
            "SELECT status, invoice_ref FROM service_fee_ledger WHERE id = :id"),
            {"id": result["entry_id"]})).first()
        assert row[0] == "INVOICED"
        assert row[1] == "INV-0001"


class TestVerifyChain:
    @pytest.mark.asyncio
    async def test_clean_chain_reports_ok(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        await fl.charge_if_eligible(db, order_id)
        result = await fl.verify_chain(db, seed["outlet_id"])
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_tampered_row_is_detected(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        charged = await fl.charge_if_eligible(db, order_id)

        # Simulate out-of-band corruption: temporarily disable the
        # immutability trigger to write a bad hash directly, the only way
        # to construct this scenario at all given the trigger otherwise
        # refuses every such UPDATE (proven by TestImmutability above).
        await db.execute(text(
            "ALTER TABLE service_fee_ledger DISABLE TRIGGER service_fee_ledger_core_immutable"))
        await db.execute(text(
            "UPDATE service_fee_ledger SET entry_hash = repeat('0', 64) WHERE id = :id"),
            {"id": charged["entry_id"]})
        await db.execute(text(
            "ALTER TABLE service_fee_ledger ENABLE TRIGGER service_fee_ledger_core_immutable"))
        await db.commit()

        result = await fl.verify_chain(db, seed["outlet_id"])
        assert result["ok"] is False
        assert result["broken_id"] == charged["entry_id"]
