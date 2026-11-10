"""TASK 7 — reconciliation reports + REVIEW-event disposition.

HTTP-level tests via the real ASGI app.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.conftest import API

FIXTURE_DAY = "2026-01-15"


async def _insert_order(db, *, outlet_id, customer_id, status="COMPLETED",
                         payment_status="PAID", total_amount=100.0,
                         created_at_sql="'2026-01-15 10:00:00+05:30'") -> str:
    order_id = uuid.uuid4()
    await db.execute(text(f"""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             created_at, updated_at)
        VALUES (:id, :cust, :outlet, :status, :amt, :pstatus,
                {created_at_sql}, {created_at_sql})
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "status": status, "amt": total_amount, "pstatus": payment_status})
    await db.commit()
    return str(order_id)


async def _insert_payment_event(db, *, outlet_id, order_id, outcome, reason,
                                 event_id=None) -> str:
    row = (await db.execute(text("""
        INSERT INTO payment_events
            (provider, event_id, outlet_id, order_id, body_sha256,
             signature_valid, outcome, reason, received_at)
        VALUES ('cashfree', :event_id, :outlet_id, :order_id, 'x', true,
                :outcome, :reason, '2026-01-15 11:00:00+05:30')
        RETURNING id
    """), {"event_id": event_id or uuid.uuid4().hex, "outlet_id": str(outlet_id),
           "order_id": order_id, "outcome": outcome, "reason": reason})).first()
    await db.commit()
    return str(row[0])


class TestNoTokenIs401:
    @pytest.mark.asyncio
    async def test_admin_report_with_no_token(self, client):
        r = await client.get(f"{API}/admin/reports/daily", params={"date": FIXTURE_DAY})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_owner_report_with_no_token(self, client):
        r = await client.get(
            f"{API}/owner/outlets/{uuid.uuid4()}/reports/daily",
            params={"date": FIXTURE_DAY})
        assert r.status_code == 401


class TestOwnerCannotUseAdminRoute:
    @pytest.mark.asyncio
    async def test_owner_token_on_admin_route_is_403(self, client, seed):
        r = await client.get(
            f"{API}/admin/reports/daily", params={"date": FIXTURE_DAY},
            headers=seed["owner_auth"])
        assert r.status_code == 403


class TestOwnerCannotReadAnotherOutlet:
    @pytest.mark.asyncio
    async def test_owner_reading_another_outlet_is_403(self, client, db, seed):
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

        r = await client.get(
            f"{API}/owner/outlets/{other_outlet}/reports/daily",
            params={"date": FIXTURE_DAY}, headers=seed["owner_auth"])
        assert r.status_code == 403

        r2 = await client.get(
            f"{API}/owner/outlets/{seed['outlet_id']}/reports/daily",
            params={"date": FIXTURE_DAY}, headers=seed["owner_auth"])
        assert r2.status_code == 200, r2.text


class TestReportNumbersMatchSeededFixture:
    @pytest.mark.asyncio
    async def test_exact_counts_for_a_seeded_day(self, client, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "SERVICE_FEE_LEDGER_ENABLED", True)
        outlet_id = seed["outlet_id"]

        # 3 orders that day: 2 eligible (PICKED_UP/COMPLETED + PAID), 1 not
        # (CREATED, never paid).
        o1 = await _insert_order(db, outlet_id=outlet_id, customer_id=seed["customer_id"],
                                  status="COMPLETED", payment_status="PAID")
        o2 = await _insert_order(db, outlet_id=outlet_id, customer_id=seed["customer_id"],
                                  status="PICKED_UP", payment_status="PAID")
        o3 = await _insert_order(db, outlet_id=outlet_id, customer_id=seed["customer_id"],
                                  status="CREATED", payment_status="PENDING")

        # payment_events: 1 duplicate, 1 failed (IGNORED/status_failed),
        # 1 pending (IGNORED/status_pending), 1 amount-mismatch REVIEW.
        await _insert_payment_event(db, outlet_id=outlet_id, order_id=o1,
                                     outcome="DUPLICATE", reason="duplicate_event_id")
        await _insert_payment_event(db, outlet_id=outlet_id, order_id=o3,
                                     outcome="IGNORED", reason="status_failed")
        await _insert_payment_event(db, outlet_id=outlet_id, order_id=o3,
                                     outcome="IGNORED", reason="status_pending")
        await _insert_payment_event(db, outlet_id=outlet_id, order_id=o2,
                                     outcome="REVIEW", reason="amount_mismatch")

        # Fee ledger: charge o1 (100 paise), charge+reverse o2 (net 0).
        await db.execute(text("""
            INSERT INTO service_fee_ledger (outlet_id, order_id, entry_type, amount_paise, billing_period, created_at)
            VALUES (:o,:oid,'CHARGE',100,'2026-01', '2026-01-15 12:00:00+05:30')
        """), {"o": outlet_id, "oid": o1})
        await db.execute(text("""
            INSERT INTO service_fee_ledger (outlet_id, order_id, entry_type, amount_paise, billing_period, created_at)
            VALUES (:o,:oid,'CHARGE',100,'2026-01', '2026-01-15 12:00:00+05:30')
        """), {"o": outlet_id, "oid": o2})
        await db.execute(text("""
            INSERT INTO service_fee_ledger (outlet_id, order_id, entry_type, amount_paise, billing_period, created_at)
            VALUES (:o,:oid,'REVERSAL',100,'2026-01', '2026-01-15 12:05:00+05:30')
        """), {"o": outlet_id, "oid": o2})
        await db.commit()

        r = await client.get(
            f"{API}/admin/reports/daily",
            params={"date": FIXTURE_DAY, "outlet_id": outlet_id},
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["total_orders"] == 3
        assert body["verified_payments"] == 2       # o1, o2 PAID
        assert body["failed"] == 1
        assert body["pending"] == 1
        assert body["mismatches"] == 1
        assert body["duplicates"] == 1
        assert body["eligible_orders"] == 2          # o1, o2
        assert body["fees_paise"] == 100              # 100 (o1) + 100 - 100 (o2 net 0)
        assert body["basis"] == "verified payment evidence, not bank settlement"


class TestRejectWithoutReasonIs422:
    @pytest.mark.asyncio
    async def test_reject_without_reason_is_422(self, client, db, seed):
        o1 = await _insert_order(db, outlet_id=seed["outlet_id"],
                                  customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=o1,
            outcome="REVIEW", reason="amount_mismatch")

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_reject_with_reason_succeeds_and_appears_in_audit_history(
        self, client, db, seed
    ):
        o1 = await _insert_order(db, outlet_id=seed["outlet_id"],
                                  customer_id=seed["customer_id"])
        event_id = await _insert_payment_event(
            db, outlet_id=seed["outlet_id"], order_id=o1,
            outcome="REVIEW", reason="amount_mismatch")

        r = await client.post(
            f"{API}/admin/payment-events/{event_id}/reject",
            headers=seed["admin_auth"], json={"reason": "confirmed fraud attempt"})
        assert r.status_code == 200, r.text

        history = await client.get(f"{API}/admin/audit-logs", headers=seed["admin_auth"])
        assert history.status_code == 200
        actions = [row["action"] for row in history.json()]
        assert "payment_event_reject" in actions
