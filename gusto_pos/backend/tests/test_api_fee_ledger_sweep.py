"""TASK 3 (reconcile fix pass 2) — sweep for missing service-fee charges.

fee_ledger.find_uncharged_completed / charge_missing, plus the admin-only
HTTP routes GET /admin/fee-ledger/uncharged and
POST /admin/fee-ledger/charge-missing.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_payments import fee_ledger as fl
from tests.conftest import API

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _ledger_config(monkeypatch):
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


class TestFindUnchargedCompleted:
    async def test_finds_an_eligible_order_with_no_charge(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        found = await fl.find_uncharged_completed(db, outlet_id=seed["outlet_id"])
        assert [f["order_id"] for f in found] == [order_id]

    async def test_a_charged_order_does_not_appear(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        await fl.charge_if_eligible(db, order_id)

        found = await fl.find_uncharged_completed(db, outlet_id=seed["outlet_id"])
        assert order_id not in [f["order_id"] for f in found]

    @pytest.mark.parametrize("status,payment_status", [
        ("CREATED", "PENDING"),
        ("CANCELLED", "PENDING"),
        ("ABANDONED", "PENDING"),
        ("READY", "PENDING"),
        ("COMPLETED", "PENDING"),  # COMPLETED but payment NOT confirmed
    ])
    async def test_ineligible_orders_never_appear(
            self, db, seed, monkeypatch, status, payment_status):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status=status, payment_status=payment_status)

        found = await fl.find_uncharged_completed(db, outlet_id=seed["outlet_id"])
        assert order_id not in [f["order_id"] for f in found]


class TestChargeMissing:
    async def test_charges_every_uncharged_eligible_order(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        result = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert result["charged"] == 1
        assert result["candidates"] == 1

        rows = await _charge_rows(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE"]

    async def test_ineligible_orders_are_never_charged(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        cancelled_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="CANCELLED", payment_status="PENDING")
        unpaid_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            status="COMPLETED", payment_status="PENDING")

        result = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert result["charged"] == 0
        assert result["candidates"] == 0
        assert await _charge_rows(db, cancelled_id) == []
        assert await _charge_rows(db, unpaid_id) == []

    async def test_flag_off_charges_nothing(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        result = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert result["reason"] == "flag_off"
        assert result["charged"] == 0
        assert await _charge_rows(db, order_id) == []

    async def test_running_the_sweep_twice_charges_once(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        first = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert first["charged"] == 1

        second = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert second["charged"] == 0
        assert second["candidates"] == 0, (
            "a charged order must not even be a candidate on the next sweep")

        rows = await _charge_rows(db, order_id)
        assert len(rows) == 1, "exactly one CHARGE row, ever"

    async def test_after_an_injected_failure_the_sweep_charges_exactly_once(
            self, db, seed, monkeypatch, caplog):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        real_charge_if_eligible = fl.charge_if_eligible
        calls = {"n": 0}

        async def _fail_once(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated ledger write failure")
            return await real_charge_if_eligible(*args, **kwargs)

        monkeypatch.setattr(fl, "charge_if_eligible", _fail_once)

        with caplog.at_level("WARNING"):
            first = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert first["failed"] == 1
        assert first["charged"] == 0
        assert "fee_ledger_sweep_charge_failed" in caplog.text
        assert await _charge_rows(db, order_id) == []

        second = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert second["charged"] == 1

        rows = await _charge_rows(db, order_id)
        assert len(rows) == 1, "exactly one CHARGE row despite the earlier failure"

    async def test_one_order_s_failure_does_not_stop_the_rest_of_the_sweep(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        failing_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        ok_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        real_charge_if_eligible = fl.charge_if_eligible

        async def _fail_for_one_order(db_, order_id_, **kwargs):
            if str(order_id_) == failing_id:
                raise RuntimeError("simulated failure")
            return await real_charge_if_eligible(db_, order_id_, **kwargs)

        monkeypatch.setattr(fl, "charge_if_eligible", _fail_for_one_order)

        result = await fl.charge_missing(db, outlet_id=seed["outlet_id"])
        assert result["failed"] == 1
        assert result["charged"] == 1
        assert await _charge_rows(db, failing_id) == []
        assert [r[0] for r in await _charge_rows(db, ok_id)] == ["CHARGE"]


class TestDailyReportCompletedWithoutCharge:
    async def test_field_reports_eligible_orders_missing_a_charge(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", False)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        day = (await db.execute(text(
            "SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date FROM "
            "customer_orders WHERE id = :id"), {"id": order_id})).scalar()

        from app.modules.carevo_payments import reports_service as rs
        report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=str(day))
        assert report["completed_without_charge"] == 1


class TestAdminRoutesAreSuperAdminOnly:
    async def test_list_uncharged_with_no_token_is_401(self, client):
        r = await client.get(f"{API}/admin/fee-ledger/uncharged")
        assert r.status_code == 401

    async def test_list_uncharged_with_owner_token_is_403(self, client, seed):
        r = await client.get(
            f"{API}/admin/fee-ledger/uncharged", headers=seed["owner_auth"])
        assert r.status_code == 403

    async def test_charge_missing_with_no_token_is_401(self, client):
        r = await client.post(f"{API}/admin/fee-ledger/charge-missing")
        assert r.status_code == 401

    async def test_charge_missing_with_owner_token_is_403(self, client, seed):
        r = await client.post(
            f"{API}/admin/fee-ledger/charge-missing", headers=seed["owner_auth"])
        assert r.status_code == 403

    async def test_super_admin_can_list_and_run_the_sweep(
            self, client, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        r_list = await client.get(
            f"{API}/admin/fee-ledger/uncharged",
            params={"outlet_id": seed["outlet_id"]}, headers=seed["admin_auth"])
        assert r_list.status_code == 200, r_list.text
        assert r_list.json()["count"] == 1

        r_run = await client.post(
            f"{API}/admin/fee-ledger/charge-missing",
            params={"outlet_id": seed["outlet_id"]}, headers=seed["admin_auth"])
        assert r_run.status_code == 200, r_run.text
        assert r_run.json()["charged"] == 1

        rows = await _charge_rows(db, order_id)
        assert [r[0] for r in rows] == ["CHARGE"]
