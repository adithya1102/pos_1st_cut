"""TASK 1 (reconcile fix pass 3) -- flags-off means zero extra SQL.

verify_pickup, collect_order and mark_refund_done each run a best-effort
service-fee ledger write wrapped in its own SAVEPOINT (begin_nested), plus
-- for the two that read back ORM-dirty order fields -- an explicit flush()
immediately before it. All three now gate that ENTIRE block (flush +
SAVEPOINT + fee call) behind SERVICE_FEE_LEDGER_ENABLED at the call site,
not just inside the fee_ledger functions themselves -- with the flag off,
the block must never touch the wire at all.

Proven two ways per flow:
  1. A real statement listener on the engine's sync connection: no SQL
     text containing "SAVEPOINT" appears with the flag off; one does with
     the flag on.
  2. A counting wrapper around the session's own `flush()` coroutine: zero
     explicit calls with the flag off.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import event, text

from app.core.config import settings
from app.core.database import engine
from app.modules.carevo_admin.service import AdminService
from app.modules.carevo_customer.service import CarevoService

pytestmark = pytest.mark.asyncio

_ACTOR = SimpleNamespace(id=uuid.uuid4(), username="test-admin")


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


class _StatementCapture:
    """Records every statement sent to the real connection for this test."""

    def __init__(self):
        self.statements: list[str] = []

    def __enter__(self):
        def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            self.statements.append(statement)

        self._fn = _before_cursor_execute
        event.listen(engine.sync_engine, "before_cursor_execute", self._fn)
        return self

    def __exit__(self, *exc):
        event.remove(engine.sync_engine, "before_cursor_execute", self._fn)

    def count_containing(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


def _count_flush_calls(monkeypatch, db):
    calls = {"n": 0}
    original = db.flush

    async def _counting_flush(*args, **kwargs):
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(db, "flush", _counting_flush)
    return calls


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


class TestVerifyPickupFlagGating:
    async def test_flag_off_issues_no_savepoint_and_no_extra_flush(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await CarevoService.verify_pickup(
                db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True

        assert cap.count_containing("SAVEPOINT") == 0
        assert cap.count_containing("RELEASE") == 0
        assert calls["n"] == 0, "no extra flush() with the flag off"

    async def test_flag_on_issues_a_savepoint(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="PAID", payment_status="PAID")

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await CarevoService.verify_pickup(
                db, uuid.UUID(order_id), "ABC123", uuid.UUID(seed["outlet_id"]))
        assert result["verified"] is True

        assert cap.count_containing("SAVEPOINT") >= 1
        assert calls["n"] >= 1, "the explicit flush() must still run with the flag on"


class TestCollectOrderFlagGating:
    async def test_flag_off_issues_no_savepoint_and_no_extra_flush(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await CarevoService.collect_order(
                db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                pickup_code="ABC123", method="cash",
                actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True

        assert cap.count_containing("SAVEPOINT") == 0
        assert cap.count_containing("RELEASE") == 0
        assert calls["n"] == 0, "no extra flush() with the flag off"

    async def test_flag_on_issues_a_savepoint(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_pickup_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="READY", payment_status="PENDING", payment_mode="PAY_AT_PICKUP")

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await CarevoService.collect_order(
                db, uuid.UUID(order_id), uuid.UUID(seed["outlet_id"]),
                pickup_code="ABC123", method="cash",
                actor_user_id=uuid.UUID(seed["owner_id"]))
        assert result["collected"] is True

        assert cap.count_containing("SAVEPOINT") >= 1
        assert calls["n"] >= 1, "the explicit flush() must still run with the flag on"


class TestMarkRefundDoneFlagGating:
    async def test_flag_off_issues_no_savepoint_and_no_extra_flush(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_refund_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert result["refund_required"] is False

        assert cap.count_containing("SAVEPOINT") == 0
        assert cap.count_containing("RELEASE") == 0
        assert calls["n"] == 0, "no extra flush() with the flag off"

    async def test_flag_on_issues_a_savepoint(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_refund_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        from app.modules.carevo_payments import fee_ledger as fl
        await fl.charge_if_eligible(db, order_id)

        calls = _count_flush_calls(monkeypatch, db)
        with _StatementCapture() as cap:
            result = await AdminService.mark_refund_done(db, order_id, actor=_ACTOR)
        assert result["refund_required"] is False

        assert cap.count_containing("SAVEPOINT") >= 1
