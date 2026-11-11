"""TASK 2 (reconcile fix pass 3) -- charge_missing commits per item.

Previously every candidate in a sweep ran inside its own SAVEPOINT but all
of them shared ONE outer transaction, committed once at the very end. The
chain-building trigger (migration 041) takes a per-outlet
pg_advisory_xact_lock that is held for the rest of whatever transaction it
ran in -- so the first candidate's lock stayed held across every other
candidate in the batch, for the whole sweep, blocking any other session
that needed that outlet's lock (e.g. a customer completing a live order
and triggering its own real-time charge).

charge_missing now commits immediately after each candidate, releasing
that lock between items. It also takes a `limit` (default 200) and
reports `processed` / `remaining` so a caller can keep calling it to drain
a large backlog.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.carevo_payments import fee_ledger as fl

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
    monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
    monkeypatch.setattr(settings, "SERVICE_FEE_PAISE", 100)
    yield


async def _insert_order(db, *, outlet_id, customer_id, status="COMPLETED",
                         payment_status="PAID", total_amount=100.0) -> str:
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


async def _charge_rows(db, order_id):
    return (await db.execute(text(
        "SELECT entry_type FROM service_fee_ledger WHERE order_id = :id"),
        {"id": order_id})).fetchall()


class TestLockReleasedBetweenItems:
    async def test_a_second_session_can_take_the_lock_after_item_one_commits(
            self, db, seed, monkeypatch):
        outlet_id = seed["outlet_id"]
        order1 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])
        order2 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])

        real_charge_if_eligible = fl.charge_if_eligible
        probe_result = {}

        async def _probe_after_first_commit(db_, order_id_, **kwargs):
            result = await real_charge_if_eligible(db_, order_id_, **kwargs)
            if order_id_ == order1 and "acquired" not in probe_result:
                async with AsyncSessionLocal() as other:
                    key = (await other.execute(
                        text("SELECT hashtextextended(:o, 0)"),
                        {"o": str(outlet_id)})).scalar()
                    acquired = (await other.execute(
                        text("SELECT pg_try_advisory_xact_lock(:k)"),
                        {"k": key})).scalar()
                    probe_result["acquired"] = acquired
                    await other.rollback()
            return result

        monkeypatch.setattr(fl, "charge_if_eligible", _probe_after_first_commit)

        result = await fl.charge_missing(db, outlet_id=outlet_id)

        assert probe_result["acquired"] is True, (
            "a second session must be able to take this outlet's advisory "
            "lock once the first candidate's own transaction has committed "
            "-- the lock must not still be held by the sweep's session")
        assert result["charged"] == 2
        assert [r[0] for r in await _charge_rows(db, order1)] == ["CHARGE"]
        assert [r[0] for r in await _charge_rows(db, order2)] == ["CHARGE"]

    async def test_no_advisory_lock_is_held_between_items(
            self, db, seed, monkeypatch):
        outlet_id = seed["outlet_id"]
        for _ in range(3):
            await _insert_order(
                db, outlet_id=outlet_id, customer_id=seed["customer_id"])

        real_charge_if_eligible = fl.charge_if_eligible
        held_counts = []

        async def _record_locks_held(db_, order_id_, **kwargs):
            held_counts.append((await db_.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")
            )).scalar())
            return await real_charge_if_eligible(db_, order_id_, **kwargs)

        monkeypatch.setattr(fl, "charge_if_eligible", _record_locks_held)

        await fl.charge_missing(db, outlet_id=outlet_id)

        assert held_counts == [0, 0, 0], (
            "no candidate should see an advisory lock still held from a "
            "PRIOR candidate in the same sweep -- each item's lock must be "
            "released (by that item's own commit) before the next starts")


class TestFailurePartiallyCommits:
    async def test_a_failure_on_the_third_item_leaves_the_first_two_committed(
            self, db, seed, monkeypatch):
        outlet_id = seed["outlet_id"]
        order1 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])
        order2 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])
        order3 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])

        real_charge_if_eligible = fl.charge_if_eligible

        async def _fail_on_third(db_, order_id_, **kwargs):
            if order_id_ == order3:
                raise RuntimeError("simulated failure on item 3")
            return await real_charge_if_eligible(db_, order_id_, **kwargs)

        monkeypatch.setattr(fl, "charge_if_eligible", _fail_on_third)

        result = await fl.charge_missing(db, outlet_id=outlet_id)

        assert result["charged"] == 2
        assert result["failed"] == 1
        assert [r[0] for r in await _charge_rows(db, order1)] == ["CHARGE"]
        assert [r[0] for r in await _charge_rows(db, order2)] == ["CHARGE"]
        assert await _charge_rows(db, order3) == []


class TestLimitAndRemaining:
    async def test_limit_is_respected_and_remaining_is_reported(
            self, db, seed):
        outlet_id = seed["outlet_id"]
        order_ids = [
            await _insert_order(db, outlet_id=outlet_id, customer_id=seed["customer_id"])
            for _ in range(5)
        ]

        first = await fl.charge_missing(db, outlet_id=outlet_id, limit=2)
        assert first["candidates"] == 5
        assert first["processed"] == 2
        assert first["charged"] == 2
        assert first["remaining"] == 3

        charged_so_far = 0
        for oid in order_ids:
            if [r[0] for r in await _charge_rows(db, oid)] == ["CHARGE"]:
                charged_so_far += 1
        assert charged_so_far == 2

        second = await fl.charge_missing(db, outlet_id=outlet_id, limit=200)
        assert second["candidates"] == 3
        assert second["processed"] == 3
        assert second["charged"] == 3
        assert second["remaining"] == 0

        for oid in order_ids:
            assert [r[0] for r in await _charge_rows(db, oid)] == ["CHARGE"]

    async def test_default_limit_is_200(self):
        import inspect
        sig = inspect.signature(fl.charge_missing)
        assert sig.parameters["limit"].default == 200


class TestRunningTwiceCommitsEachOnce:
    async def test_running_the_sweep_twice_charges_each_order_once(
            self, db, seed):
        outlet_id = seed["outlet_id"]
        order1 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])
        order2 = await _insert_order(
            db, outlet_id=outlet_id, customer_id=seed["customer_id"])

        first = await fl.charge_missing(db, outlet_id=outlet_id)
        assert first["charged"] == 2

        second = await fl.charge_missing(db, outlet_id=outlet_id)
        assert second["charged"] == 0
        assert second["candidates"] == 0

        assert [r[0] for r in await _charge_rows(db, order1)] == ["CHARGE"]
        assert [r[0] for r in await _charge_rows(db, order2)] == ["CHARGE"]
