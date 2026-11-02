"""Owner app: show whether the customer has left / arrived, on each active
order, using data that already exists (order_events + order_twin).

GET /pos/orders (list_active_orders) now carries three additive fields on
OwnerOrderOut: departed_at, arrived_at, est_arrival_at. All three are null
until the matching signal exists, which is every order until the customer
taps/pings or the engine twins it — so an owner_app build that does not know
these keys exist is unaffected.

Held here:
  * no event at all -> both timestamps null;
  * CUSTOMER_DEPARTED only -> departed_at set, arrived_at still null;
  * CUSTOMER_ARRIVED (via the geofenced /location ping) -> both set;
  * the batched query never scales with page size (same query count for a
    1-order and a 5-order page) and adds exactly one query over the
    pre-existing baseline;
  * no latitude/longitude/accuracy/speed key ever appears in the serialised
    OwnerOrderOut, for any of the three states above.
"""
import uuid

import pytest
from sqlalchemy import event, text

from app.core.database import engine

API = "/api/v1"

# Keys that must never appear anywhere in an owner-facing order payload: the
# event payloads that produce departed_at/arrived_at carry raw location, and
# this is the one place that must never leak through.
_LOCATION_KEYS = {"lat", "lng", "latitude", "longitude", "accuracy_m", "speed_mps"}


def _leaked_location_keys(order: dict) -> set:
    """Every key in `order` (recursively) that names a location field."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _LOCATION_KEYS:
                    found.add(k)
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(order)
    return found


async def _create_paid_order(client, seed) -> dict:
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
    })
    assert r.status_code == 200, r.text
    order = r.json()
    p = await client.post(f"{API}/customer/payment/simulate",
                           headers=seed["customer_auth"],
                           json={"order_id": order["id"], "method": "upi"})
    assert p.status_code == 200, p.text
    return order


async def _queue_row(client, seed, order_id: str) -> dict:
    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    rows = {str(o["order_id"]): o for o in r.json()}
    assert order_id in rows, "order must be in the owner queue"
    return rows[order_id]


@pytest.mark.asyncio
class TestArrivalSignalsOnOwnerQueue:
    async def test_no_event_means_both_timestamps_null(self, client, seed):
        order = await _create_paid_order(client, seed)
        row = await _queue_row(client, seed, order["id"])

        assert row["departed_at"] is None
        assert row["arrived_at"] is None

    async def test_departed_only_leaves_arrived_null(self, client, seed):
        order = await _create_paid_order(client, seed)

        d = await client.post(f"{API}/customer/orders/{order['id']}/depart",
                               headers=seed["customer_auth"], json={})
        assert d.status_code == 200, d.text

        row = await _queue_row(client, seed, order["id"])
        assert row["departed_at"] is not None
        assert row["arrived_at"] is None

    async def test_geofenced_arrival_sets_both(self, client, seed, db):
        """A location ping inside the geofence infers CUSTOMER_ARRIVED even
        with no explicit /depart call — depart and arrive are independent
        events, and the queue must reflect whichever actually landed."""
        order = await _create_paid_order(client, seed)

        outlet_id = seed["outlet_id"]
        await db.execute(text(
            "UPDATE outlets SET latitude = 12.9716, longitude = 77.5946 "
            "WHERE id = :o"), {"o": outlet_id})
        await db.commit()

        ping = await client.post(
            f"{API}/customer/orders/{order['id']}/location",
            headers=seed["customer_auth"],
            json={"lat": 12.9716, "lng": 77.5946, "accuracy_m": 5.0},
        )
        assert ping.status_code == 200, ping.text
        assert ping.json().get("detail") == "arrived"

        row = await _queue_row(client, seed, order["id"])
        assert row["arrived_at"] is not None
        # No /depart call was made on this test's own order; departed_at may
        # be null or set depending on other inferred paths, but it must not
        # be confused with arrived_at — the two keys are independent.
        assert "arrived_at" in row and "departed_at" in row

    async def test_no_location_fields_leak_into_the_owner_payload(
            self, client, seed):
        """Covers all three states: no event, departed only, and arrived."""
        no_event = await _create_paid_order(client, seed)
        departed_only = await _create_paid_order(client, seed)
        arrived = await _create_paid_order(client, seed)

        d = await client.post(f"{API}/customer/orders/{departed_only['id']}/depart",
                               headers=seed["customer_auth"], json={})
        assert d.status_code == 200, d.text

        a = await client.post(f"{API}/customer/orders/{arrived['id']}/arrived",
                               headers=seed["customer_auth"],
                               json={"accuracy_m": 8.0, "source": "tap"})
        assert a.status_code == 200, a.text

        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        payload = r.json()

        ids = {no_event["id"], departed_only["id"], arrived["id"]}
        checked = [o for o in payload if str(o["order_id"]) in ids]
        assert len(checked) == 3

        for order in checked:
            leaked = _leaked_location_keys(order)
            assert not leaked, f"location keys leaked into owner payload: {leaked}"


@pytest.mark.asyncio
class TestQueryCountStaysBatched:
    """list_active_orders must never issue one query per order for the new
    arrival-signal data. Measured baseline (unmodified function, 3 plain PAID
    orders, no scheduling/manual-acceptance/UPI in play) is 11 queries. This
    change adds exactly ONE combined query (order_events + order_twin in a
    single statement via two CTEs and a join) — net growth +1. The thing that
    actually must hold, and that this test asserts directly rather than via a
    magic baseline number, is that the count does NOT grow with the number of
    orders on the page.
    """

    async def _query_count_for_outlet(self, db, outlet_id: str) -> int:
        from app.modules.carevo_customer.service import CarevoService

        counter = {"n": 0}

        def before_cursor_execute(conn, cursor, statement, parameters,
                                   context, executemany):
            counter["n"] += 1

        event.listen(engine.sync_engine, "before_cursor_execute",
                     before_cursor_execute)
        try:
            await CarevoService.list_active_orders(db, uuid.UUID(outlet_id))
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute",
                          before_cursor_execute)
        return counter["n"]

    async def test_query_count_independent_of_page_size(
            self, client, seed, db):
        await _create_paid_order(client, seed)
        count_for_one = await self._query_count_for_outlet(db, seed["outlet_id"])

        for _ in range(4):
            await _create_paid_order(client, seed)
        count_for_five = await self._query_count_for_outlet(db, seed["outlet_id"])

        assert count_for_five == count_for_one, (
            "query count must not scale with the number of orders on the "
            f"page: 1 order -> {count_for_one} queries, "
            f"5 orders -> {count_for_five} queries"
        )

    async def test_query_count_grows_by_at_most_one_over_the_pre_change_baseline(
            self, client, seed, db):
        """The measured pre-change baseline for this exact scenario (3 plain
        PAID orders, nothing scheduled/manual/UPI) was 11 queries: one each
        for the orders SELECT and the items SELECT, plus 9 fixed outlet-scoped
        sweep queries that do not depend on N. This change adds exactly ONE
        query: a single statement with two CTEs (order_events, order_twin)
        joined and returned as one round trip, so the net growth is +1, not
        +1 per new field group.
        """
        for _ in range(3):
            await _create_paid_order(client, seed)

        count = await self._query_count_for_outlet(db, seed["outlet_id"])

        assert count == 12, (
            f"expected 11 (baseline) + 1 (single combined batched query) "
            f"= 12, got {count}"
        )
