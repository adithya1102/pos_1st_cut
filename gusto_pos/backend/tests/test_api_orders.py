"""Cart pre-check, checkout/payment, and the order lifecycle."""
import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio


class TestCart:
    """Cart itself is client-side; these are the API-testable parts."""

    async def test_cart_check_passes_for_available_items(self, client, seed):
        r = await client.post(f"{API}/customer/cart/check", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "menu_item_ids": [seed["menu_item_id"]]})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["unavailable"] == []

    async def test_cart_check_flags_unavailable_item(self, client, seed, db):
        await db.execute(text("UPDATE menu_items SET is_available=false WHERE id=:i"),
                         {"i": seed["menu_item_id"]})
        await db.commit()
        r = await client.post(f"{API}/customer/cart/check", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "menu_item_ids": [seed["menu_item_id"]]})
        assert r.json()["ok"] is False
        assert r.json()["unavailable"][0]["menu_item_id"] == seed["menu_item_id"]

    async def test_menu_hides_unavailable_items(self, client, seed, db):
        await db.execute(text("UPDATE menu_items SET is_available=false WHERE id=:i"),
                         {"i": seed["menu_item_id"]})
        await db.commit()
        r = await client.get(f"{API}/customer/menu/{seed['outlet_id']}",
                             headers=seed["customer_auth"])
        ids = [i["id"] for c in r.json()["categories"] for i in c["items"]]
        assert seed["menu_item_id"] not in ids


class TestCheckout:
    async def test_create_order_returns_price_breakdown(self, client, seed):
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}]})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["original_amount"] == 200.0
        assert b["discount_amount"] == 0.0
        assert b["final_amount"] == b["total_amount"] == 200.0
        assert "payment" in b and b["payment"]["gateway"]

    async def test_create_order_rejects_unavailable_item(self, client, seed, db):
        await db.execute(text("UPDATE menu_items SET is_available=false WHERE id=:i"),
                         {"i": seed["menu_item_id"]})
        await db.commit()
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
        assert r.status_code == 409

    async def test_create_order_rejects_unknown_item(self, client, seed):
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": "00000000-0000-0000-0000-000000000000",
                       "quantity": 1}]})
        assert r.status_code == 400

    async def test_payment_marks_paid_and_issues_pickup_code(self, client, seed, paid_order):
        r = await client.get(f"{API}/customer/orders/{paid_order['id']}",
                             headers=seed["customer_auth"])
        body = r.json()
        assert body["payment_status"] == "PAID"
        assert body["pickup_code"] and len(body["pickup_code"]) >= 4

    async def test_paid_order_emits_the_pe_event_chain(self, client, seed, paid_order, db):
        rows = (await db.execute(text(
            "SELECT event_type FROM order_events WHERE order_id=:o ORDER BY seq"),
            {"o": paid_order["id"]})).fetchall()
        evs = {r[0] for r in rows}
        # mark_paid must STILL infer acceptance + prep start; the prediction
        # engine anchors its twin on these.
        assert {"ORDER_CREATED", "ORDER_PAID", "ORDER_ACCEPTED", "PREP_STARTED"} <= evs

    async def test_payment_is_idempotent(self, client, seed, paid_order, db):
        before = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o AND event_type='ORDER_PAID'"),
            {"o": paid_order["id"]})
        await client.post(f"{API}/customer/payment/simulate", headers=seed["customer_auth"],
                          json={"order_id": paid_order["id"], "method": "upi"})
        after = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o AND event_type='ORDER_PAID'"),
            {"o": paid_order["id"]})
        assert before == after == 1


class TestOrderLifecycle:
    async def test_reject_paid_order_cancels_it(self, client, seed, paid_order, db):
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/reject",
                              headers=seed["owner_auth"], json={"reason": "kitchen closed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED"
        evs = [x[0] for x in (await db.execute(text(
            "SELECT event_type FROM order_events WHERE order_id=:o"),
            {"o": paid_order["id"]})).fetchall()]
        assert "ORDER_REJECTED" in evs

    async def test_reject_is_idempotent(self, client, seed, paid_order):
        await client.post(f"{API}/pos/orders/{paid_order['id']}/reject",
                          headers=seed["owner_auth"])
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/reject",
                              headers=seed["owner_auth"])
        assert r.status_code == 200
        assert r.json()["already"] is True

    async def test_ready_order_cannot_be_rejected(self, client, seed, paid_order, db):
        await db.execute(text("UPDATE customer_orders SET status='READY' WHERE id=:o"),
                         {"o": paid_order["id"]})
        await db.commit()
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/reject",
                              headers=seed["owner_auth"])
        assert r.status_code == 409

    async def test_mark_paid_endpoint_is_gone(self, client, seed, paid_order):
        """Removed deliberately: with a real gateway it is a button that marks
        unpaid orders paid."""
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/mark-paid",
                              headers=seed["owner_auth"])
        assert r.status_code == 404

    async def test_batch_item_unavailable(self, client, seed, paid_order, db):
        items = (await db.execute(text(
            "SELECT id FROM customer_order_items WHERE customer_order_id=:o"),
            {"o": paid_order["id"]})).fetchall()
        ids = [str(i[0]) for i in items]
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/items/unavailable",
                              headers=seed["owner_auth"], json={"item_ids": ids})
        assert r.status_code == 200, r.text
        assert len(r.json()["marked"]) == len(ids)
        n = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o AND event_type='ITEM_UNAVAILABLE'"),
            {"o": paid_order["id"]})
        assert n == len(ids), "one event PER item, not per batch"

    async def test_item_unavailable_rejects_foreign_line_item(self, client, seed, paid_order):
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/items/unavailable",
                              headers=seed["owner_auth"],
                              json={"item_ids": ["00000000-0000-0000-0000-000000000000"]})
        assert r.status_code == 400

    async def test_order_total_unchanged_by_item_unavailable(self, client, seed,
                                                             paid_order, db):
        items = [str(i[0]) for i in (await db.execute(text(
            "SELECT id FROM customer_order_items WHERE customer_order_id=:o"),
            {"o": paid_order["id"]})).fetchall()]
        await client.post(f"{API}/pos/orders/{paid_order['id']}/items/unavailable",
                          headers=seed["owner_auth"], json={"item_ids": items})
        total = await db.scalar(text("SELECT total_amount FROM customer_orders WHERE id=:o"),
                                {"o": paid_order["id"]})
        assert float(total) == 200.0, "the paid order's total must not be adjusted"

    async def test_item_unavailable_blocked_once_ready(self, client, seed, paid_order, db):
        """Item 3 cutoff: composition cannot change once the food is made."""
        items = [str(i[0]) for i in (await db.execute(text(
            "SELECT id FROM customer_order_items WHERE customer_order_id=:o"),
            {"o": paid_order["id"]})).fetchall()]
        await db.execute(text("UPDATE customer_orders SET status='READY' WHERE id=:o"),
                         {"o": paid_order["id"]})
        await db.commit()

        batch = await client.post(f"{API}/pos/orders/{paid_order['id']}/items/unavailable",
                                  headers=seed["owner_auth"], json={"item_ids": items})
        assert batch.status_code == 409
        assert "ready for pickup" in batch.json()["detail"]

        # the older single-item path must be closed too, not just the checklist
        single = await client.post(f"{API}/pos/orders/{paid_order['id']}/notify",
                                   headers=seed["owner_auth"],
                                   json={"type": "item_unavailable", "item_id": items[0]})
        assert single.status_code == 409

        n = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='ITEM_UNAVAILABLE'"), {"o": paid_order["id"]})
        assert n == 0, "a rejected cutoff must write no event"

    async def test_item_unavailable_still_allowed_before_ready(self, client, seed,
                                                               paid_order, db):
        for status in ("PAID", "RECEIVED", "PREPARING"):
            await db.execute(text("UPDATE customer_orders SET status=:s WHERE id=:o"),
                             {"s": status, "o": paid_order["id"]})
            await db.commit()
            items = [str(i[0]) for i in (await db.execute(text(
                "SELECT id FROM customer_order_items WHERE customer_order_id=:o"),
                {"o": paid_order["id"]})).fetchall()]
            r = await client.post(f"{API}/pos/orders/{paid_order['id']}/items/unavailable",
                                  headers=seed["owner_auth"], json={"item_ids": items[:1]})
            assert r.status_code == 200, f"{status} should still allow it: {r.text}"
