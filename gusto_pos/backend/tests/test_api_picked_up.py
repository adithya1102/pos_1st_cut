"""Customer "I've picked this up" ack — the new server record (migration 023)
and the departed/arrived/picked_up fields on OrderOut.

The ack used to be an on-device flag with zero server trace. These tests hold
the contract of its replacement:

  * the endpoint records ONE append-only CUSTOMER_PICKED_UP event, idempotently;
  * it moves NO order status (staff PICKUP_VERIFIED is still the only real
    completion);
  * only the order's owner may call it;
  * GET /customer/orders/{id} now reports departed / arrived / picked_up, all
    defaulting False and flipping True as the matching event is recorded.
"""
import uuid

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.deps import create_customer_token

API = "/api/v1"


async def _events(db, order_id, event_type):
    return await db.scalar(text(
        "SELECT count(*) FROM order_events WHERE order_id=:o AND event_type=:t"
    ), {"o": str(order_id), "t": event_type})


@pytest.mark.asyncio
class TestPickedUpEndpoint:
    async def test_records_one_event_and_reports_picked_up(
            self, client, db, seed, paid_order):
        oid = paid_order["id"]

        # Before: no ack event, and OrderOut reports picked_up False.
        assert await _events(db, oid, "CUSTOMER_PICKED_UP") == 0
        before = (await client.get(
            f"{API}/customer/orders/{oid}", headers=seed["customer_auth"])).json()
        assert before["picked_up"] is False

        r = await client.post(
            f"{API}/customer/orders/{oid}/picked-up", headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "recorded": True, "detail": None}

        assert await _events(db, oid, "CUSTOMER_PICKED_UP") == 1
        after = (await client.get(
            f"{API}/customer/orders/{oid}", headers=seed["customer_auth"])).json()
        assert after["picked_up"] is True

    async def test_is_idempotent(self, client, db, seed, paid_order):
        oid = paid_order["id"]
        first = await client.post(
            f"{API}/customer/orders/{oid}/picked-up", headers=seed["customer_auth"])
        second = await client.post(
            f"{API}/customer/orders/{oid}/picked-up", headers=seed["customer_auth"])

        assert first.json()["recorded"] is True
        assert second.status_code == 200
        assert second.json()["recorded"] is False
        assert second.json()["detail"] == "already acknowledged"
        # Still exactly one row — the append-only log is not duplicated.
        assert await _events(db, oid, "CUSTOMER_PICKED_UP") == 1

    async def test_does_not_move_order_status(
            self, client, seed, paid_order):
        oid = paid_order["id"]
        before = (await client.get(
            f"{API}/customer/orders/{oid}", headers=seed["customer_auth"])).json()

        await client.post(
            f"{API}/customer/orders/{oid}/picked-up", headers=seed["customer_auth"])

        after = (await client.get(
            f"{API}/customer/orders/{oid}", headers=seed["customer_auth"])).json()
        # The ack is a courtesy: status is untouched, never advanced to a
        # completed state by the customer tapping it.
        assert after["status"] == before["status"]
        assert after["status"].upper() not in {"COMPLETED", "PICKED_UP"}

    async def test_only_the_owner_may_ack(self, client, db, seed, paid_order):
        # A second, real customer — get_current_customer must resolve the token
        # to an existing row, so a bare fake id would 401, not 403.
        other_id = uuid.uuid4()
        await db.execute(text(
            "INSERT INTO customers (id, phone_number, name, points_balance, created_at) "
            "VALUES (:i,:p,'Intruder', 0, now())"),
            {"i": str(other_id), "p": f"+9188{seed['tag'][:8]}"})
        await db.commit()
        other_auth = {"Authorization": f"Bearer {create_customer_token(str(other_id))}"}

        r = await client.post(
            f"{API}/customer/orders/{paid_order['id']}/picked-up", headers=other_auth)
        assert r.status_code == 403, r.text
        # And nothing was recorded against the order.
        assert await _events(db, paid_order["id"], "CUSTOMER_PICKED_UP") == 0

    async def test_unknown_order_is_404(self, client, seed):
        r = await client.post(
            f"{API}/customer/orders/{uuid.uuid4()}/picked-up",
            headers=seed["customer_auth"])
        assert r.status_code == 404


@pytest.mark.asyncio
class TestOrderOutPickupFlags:
    async def test_flags_default_false_on_a_fresh_order(
            self, client, seed, paid_order):
        r = await client.get(
            f"{API}/customer/orders/{paid_order['id']}",
            headers=seed["customer_auth"])
        assert r.status_code == 200
        body = r.json()
        assert body["departed"] is False
        assert body["arrived"] is False
        assert body["picked_up"] is False

    async def test_flags_reflect_departed_and_arrived(
            self, client, seed, paid_order):
        oid = paid_order["id"]
        auth = seed["customer_auth"]

        await client.post(f"{API}/customer/orders/{oid}/depart", headers=auth, json={})
        await client.post(f"{API}/customer/orders/{oid}/arrived", headers=auth,
                          json={"source": "tap"})

        body = (await client.get(
            f"{API}/customer/orders/{oid}", headers=auth)).json()
        assert body["departed"] is True
        assert body["arrived"] is True
        # picked_up is independent and untouched by the travel taps.
        assert body["picked_up"] is False

    async def test_all_three_can_be_true_together(
            self, client, seed, paid_order):
        oid = paid_order["id"]
        auth = seed["customer_auth"]
        await client.post(f"{API}/customer/orders/{oid}/depart", headers=auth, json={})
        await client.post(f"{API}/customer/orders/{oid}/arrived", headers=auth,
                          json={"source": "tap"})
        await client.post(f"{API}/customer/orders/{oid}/picked-up", headers=auth)

        body = (await client.get(
            f"{API}/customer/orders/{oid}", headers=auth)).json()
        assert (body["departed"], body["arrived"], body["picked_up"]) == \
            (True, True, True)
