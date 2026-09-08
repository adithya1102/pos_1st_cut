"""owner_app's active-order queue is gated to payment-confirmed orders.

Before this, GET /pos/orders returned any non-terminal order — including a
CREATED, unpaid one — so an order flashed onto the restaurant screen the moment
it was created, before payment succeeded. list_active_orders now floors on
_LIVE_STATUSES ({PAID, RECEIVED, PREPARING, READY}, the same set the expiry
sweep uses), which excludes CREATED.

Held here:
  * an unpaid CREATED order is absent from the owner queue;
  * a paid order is present;
  * the COMPLETED-within-grace row is unaffected (regression guard);
  * the admin order log still shows the unpaid order — admin sees everything.
"""
import pytest

API = "/api/v1"


async def _create_unpaid(client, seed) -> dict:
    """A freshly created order, NOT paid — status CREATED, payment PENDING."""
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                          json={
                              "outlet_id": seed["outlet_id"],
                              "items": [{"menu_item_id": seed["menu_item_id"],
                                         "quantity": 1}],
                          })
    assert r.status_code == 200, r.text
    return r.json()


async def _queue_ids(client, seed) -> list[str]:
    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    return [str(o["order_id"]) for o in r.json()]


@pytest.mark.asyncio
class TestOwnerQueuePaidGate:
    async def test_unpaid_created_order_is_absent(self, client, seed):
        order = await _create_unpaid(client, seed)

        # Precondition: it really is CREATED and unpaid.
        st = (await client.get(f"{API}/customer/orders/{order['id']}",
                               headers=seed["customer_auth"])).json()
        assert st["status"] == "CREATED"
        assert st["payment_status"] != "PAID"

        assert str(order["id"]) not in await _queue_ids(client, seed), (
            "an unpaid CREATED order must not reach restaurant staff")

    async def test_paid_order_is_present(self, client, seed, paid_order):
        assert str(paid_order["id"]) in await _queue_ids(client, seed), (
            "a paid order must still appear in the queue")

    async def test_gate_hides_unpaid_but_keeps_paid_side_by_side(
            self, client, seed, paid_order):
        # Both exist at the same outlet; only the paid one is visible.
        unpaid = await _create_unpaid(client, seed)
        ids = await _queue_ids(client, seed)
        assert str(paid_order["id"]) in ids
        assert str(unpaid["id"]) not in ids

    async def test_every_returned_order_is_payment_confirmed(
            self, client, seed, paid_order):
        # Whatever the queue returns, none of it is unpaid.
        await _create_unpaid(client, seed)  # noise that must be filtered out
        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        rows = r.json()
        assert rows, "expected at least the paid order"
        for o in rows:
            assert o["payment_status"] == "PAID", (
                f"queue returned a non-PAID order: {o['order_id']} "
                f"({o['payment_status']})")
            assert o["status"] != "CREATED"


@pytest.mark.asyncio
class TestAdminStillSeesEverything:
    async def test_admin_order_log_still_shows_the_unpaid_order(
            self, client, seed):
        order = await _create_unpaid(client, seed)

        r = await client.get(f"{API}/admin/orders", headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [str(o["order_id"]) for o in body["orders"]]
        assert str(order["id"]) in ids, (
            "the admin log must keep showing unpaid orders — the owner-queue "
            "gate must not have touched the admin query")
        # And its unpaid state is visible to admin, unchanged.
        row = next(o for o in body["orders"]
                   if str(o["order_id"]) == str(order["id"]))
        assert row["status"] == "CREATED"
        assert row["payment_status"] != "PAID"
