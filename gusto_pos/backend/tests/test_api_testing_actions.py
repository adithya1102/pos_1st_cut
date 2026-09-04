"""Testing-dashboard manual Approve / Reject + the IST placed-at column.

Approve and Reject reuse the EXACT staff service functions — advance_status and
CarevoService.reject_order — so this asserts the real effects (RECEIVED on
approve, CANCELLED on reject) and that the server-computed can_approve/can_reject
flags gate the buttons to the states the real endpoints actually accept.
"""
import re
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_customer.service import CarevoService

API = "/api/v1"
KEY = "test-dash-key"
HDR = {"X-Testing-Key": KEY}
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _configure_key():
    prev = settings.TESTING_DASHBOARD_KEY
    settings.TESTING_DASHBOARD_KEY = KEY
    yield
    settings.TESTING_DASHBOARD_KEY = prev


async def _orders(client):
    r = await client.get(f"{API}/testing/orders", headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


async def _row(client, order_id):
    return next((o for o in await _orders(client)
                 if str(o["order_id"]) == order_id), None)


async def _db_status(db, order_id):
    return await db.scalar(text(
        "SELECT status FROM customer_orders WHERE id = :o"), {"o": order_id})


# ------------------------------ Task 2: date/time -------------------------
@pytest.mark.asyncio
class TestPlacedAtIST:
    async def test_created_at_ist_is_present_and_correctly_formatted(
            self, client, seed, paid_order, db):
        row = await _row(client, paid_order["id"])
        assert row is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", row["created_at_ist"]), \
            row["created_at_ist"]
        # Exactly the DB timestamp converted to Asia/Kolkata.
        created = await db.scalar(text(
            "SELECT created_at FROM customer_orders WHERE id = :o"),
            {"o": paid_order["id"]})
        assert row["created_at_ist"] == created.astimezone(IST).strftime("%Y-%m-%d %H:%M")


# ---------------------- Task 3: action-flag gating ------------------------
@pytest.mark.asyncio
class TestActionFlags:
    async def test_paid_order_can_be_approved_and_rejected(
            self, client, seed, paid_order):
        row = await _row(client, paid_order["id"])
        assert row["status"] == "PAID"
        assert row["can_approve"] is True
        assert row["can_reject"] is True

    async def test_preparing_hides_approve_keeps_reject(
            self, client, seed, paid_order, db):
        # PREPARING is in the kitchen: no Approve, but Reject still valid (matches
        # owner_app's _rejectable and the server's REJECTABLE_STATUSES).
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="PREPARING")
        row = await _row(client, paid_order["id"])
        assert row["status"] == "PREPARING"
        assert row["can_approve"] is False
        assert row["can_reject"] is True

    async def test_ready_hides_both(self, client, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        row = await _row(client, paid_order["id"])
        assert row["status"] == "READY"
        assert row["can_approve"] is False
        assert row["can_reject"] is False


# --------------------------- Task 3: approve ------------------------------
@pytest.mark.asyncio
class TestApprove:
    async def test_approve_advances_paid_to_received(
            self, client, seed, paid_order, db):
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/approve", headers=HDR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_status"] == "PAID"
        assert body["status"] == "RECEIVED"
        assert await _db_status(db, paid_order["id"]) == "RECEIVED"

    async def test_approve_received_advances_to_preparing(
            self, client, seed, paid_order, db):
        await client.post(f"{API}/testing/orders/{paid_order['id']}/approve",
                          headers=HDR)  # PAID -> RECEIVED
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/approve", headers=HDR)
        assert r.json()["status"] == "PREPARING"
        assert await _db_status(db, paid_order["id"]) == "PREPARING"

    async def test_approve_unknown_order_404(self, client, seed):
        r = await client.post(
            f"{API}/testing/orders/{uuid.uuid4()}/approve", headers=HDR)
        assert r.status_code == 404


# --------------------------- Task 3: reject -------------------------------
@pytest.mark.asyncio
class TestReject:
    async def test_reject_cancels_order_and_records_event(
            self, client, seed, paid_order, db):
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/reject", headers=HDR,
            json={"reason": "test reject"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED"
        assert await _db_status(db, paid_order["id"]) == "CANCELLED"
        # It went through the real reject_order: an ORDER_REJECTED event exists.
        ev = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id = :o "
            "AND event_type = 'ORDER_REJECTED'"), {"o": paid_order["id"]})
        assert ev == 1

    async def test_rejected_order_drops_off_the_live_list(
            self, client, seed, paid_order):
        await client.post(f"{API}/testing/orders/{paid_order['id']}/reject",
                          headers=HDR, json={"reason": "gone"})
        # CANCELLED is filtered out of the active-orders view — the row disappears.
        assert await _row(client, paid_order["id"]) is None

    async def test_reject_on_ready_is_refused_by_the_real_endpoint(
            self, client, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/reject", headers=HDR,
            json={"reason": "too late"})
        assert r.status_code == 409, r.text
        assert await _db_status(db, paid_order["id"]) == "READY"  # unchanged


# ------------------------------ the secret gate ---------------------------
@pytest.mark.asyncio
class TestActionsGated:
    async def test_approve_and_reject_require_the_key(self, client, seed, paid_order):
        a = await client.post(f"{API}/testing/orders/{paid_order['id']}/approve")
        j = await client.post(f"{API}/testing/orders/{paid_order['id']}/reject",
                              json={})
        assert a.status_code == 401 and j.status_code == 401
