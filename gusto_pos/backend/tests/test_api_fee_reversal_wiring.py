"""TASK 4 (reconcile fix pass) — fee ledger REVERSAL wired into
AdminService.mark_refund_done, the function that actually clears
customer_orders.refund_required and records who settled it (the only
"mark an order refunded" action in this codebase; list_refund_due is a
read-only queue, not a processor).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_payments import fee_ledger as fl

pytestmark = pytest.mark.asyncio

_ACTOR = SimpleNamespace(id=uuid.uuid4(), username="test-admin")


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


async def _insert_order(db, *, outlet_id, customer_id, status="COMPLETED",
                         payment_status="PAID", refund_required=False,
                         total_amount=200.0) -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             payment_mode, refund_required, created_at, updated_at)
        VALUES (:id, :cust, :outlet, :status, :amt, :pstatus, 'PREPAID',
                :refund, now(), now())
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "status": status, "amt": total_amount, "pstatus": payment_status,
           "refund": refund_required})
    await db.commit()
    return str(order_id)


async def _ledger_rows(db, order_id):
    return (await db.execute(text(
        "SELECT entry_type, amount_paise FROM service_fee_ledger WHERE order_id = :id "
        "ORDER BY created_at"), {"id": order_id})).fetchall()


class TestRefundReversalWiring:
    async def test_refund_of_a_charged_order_writes_one_reversal(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            refund_required=True)
        charge = await fl.charge_if_eligible(db, order_id)
        assert charge["charged"] is True

        result = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert result["already"] is False
        assert result["refund_required"] is False

        rows = await _ledger_rows(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE", "REVERSAL"]
        assert rows[1][1] == 100

    async def test_refund_of_an_uncharged_order_writes_no_reversal(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="CANCELLED", payment_status="PENDING", refund_required=True)

        result = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert result["refund_required"] is False

        rows = await _ledger_rows(db, order_id)
        assert rows == []

    async def test_second_refund_call_writes_no_second_reversal(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            refund_required=True)
        await fl.charge_if_eligible(db, order_id)

        first = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert first["already"] is False

        second = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert second["already"] is True

        rows = await _ledger_rows(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE", "REVERSAL"]

    async def test_verify_chain_is_ok_after_charge_and_reversal(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            refund_required=True)
        await fl.charge_if_eligible(db, order_id)
        await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)

        result = await fl.verify_chain(db, seed["outlet_id"])
        assert result == {"ok": True}

    async def test_ledger_failure_rolls_back_the_refund_clear(self, db, seed, monkeypatch):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            refund_required=True)
        await fl.charge_if_eligible(db, order_id)

        async def _boom(*args, **kwargs):
            raise RuntimeError("ledger write exploded")

        monkeypatch.setattr(fl, "reverse_if_charged", _boom)

        with pytest.raises(RuntimeError):
            await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        await db.rollback()

        row = (await db.execute(text(
            "SELECT refund_required FROM customer_orders WHERE id = :id"),
            {"id": order_id})).first()
        assert row[0] is True, "refund_required must still be set after rollback"

        rows = await _ledger_rows(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE"]
