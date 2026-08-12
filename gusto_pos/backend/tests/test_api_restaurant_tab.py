"""GET /admin/orders/by-restaurant — the Restaurant tab's aggregation.

A VIEW over customer_orders + outlets: restaurant -> day -> time. No table and
no column was added for it, and these tests assert the shape of the tree plus
the two things that are easy to get wrong in a hand-rolled grouping — that the
per-level totals actually add up, and that the SUPER_ADMIN gate is the same one
every other admin route uses.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


async def _groups(client, seed, days: int = 30):
    r = await client.get(
        f"{API}/admin/orders/by-restaurant?days={days}",
        headers=seed["admin_auth"],
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_orders_are_grouped_restaurant_then_day_then_time(
    client, seed, paid_order
):
    groups = await _groups(client, seed)

    mine = next(
        (g for g in groups if str(g["outlet_id"]) == seed["outlet_id"]), None
    )
    assert mine is not None, "the seeded outlet should appear once it has an order"

    # Level 1 carries the restaurant's identity, not just its id — the tab is
    # unreadable if the UI has to resolve names itself.
    assert mine["outlet_name"]
    assert mine["order_count"] >= 1

    # Level 2: days.
    assert mine["days"], "a restaurant with orders must have at least one day"
    day = mine["days"][0]
    assert len(day["day"]) == 10 and day["day"][4] == "-", (
        f"day should be an ISO date, got {day['day']!r}"
    )

    # Level 3: individual orders, each with a wall-clock time.
    assert day["orders"], "a day with a count must carry its orders"
    order = next(
        (o for o in day["orders"] if str(o["order_id"]) == str(paid_order["id"])),
        None,
    )
    assert order is not None, "the seeded order should be at the leaf"
    assert len(order["time"]) == 5 and order["time"][2] == ":", (
        f"time should be HH:MM, got {order['time']!r}"
    )
    assert order["item_count"] == 2, "the fixture orders quantity 2"


@pytest.mark.asyncio
async def test_totals_add_up_at_every_level(client, seed, paid_order):
    groups = await _groups(client, seed)
    mine = next(g for g in groups if str(g["outlet_id"]) == seed["outlet_id"])

    # Day totals are the sum of their orders...
    for day in mine["days"]:
        assert day["order_count"] == len(day["orders"])
        assert day["total_amount"] == pytest.approx(
            sum(o["total_amount"] for o in day["orders"]), abs=0.01
        )

    # ...and the restaurant total is the sum of its days. A grouping bug that
    # double-counts or drops a row shows up here and nowhere else.
    assert mine["order_count"] == sum(d["order_count"] for d in mine["days"])
    assert mine["total_amount"] == pytest.approx(
        sum(d["total_amount"] for d in mine["days"]), abs=0.01
    )


@pytest.mark.asyncio
async def test_the_window_excludes_older_orders(client, seed, paid_order, db):
    from datetime import timedelta

    from sqlalchemy import text

    # Push the order 10 days back, then ask for a 7-day window.
    await db.execute(
        text(
            "UPDATE customer_orders "
            "SET created_at = now() - CAST(:ago AS interval) WHERE id = :i"
        ),
        {"ago": timedelta(days=10), "i": str(paid_order["id"])},
    )
    await db.commit()

    seven = await _groups(client, seed, days=7)
    mine_7 = next(
        (g for g in seven if str(g["outlet_id"]) == seed["outlet_id"]), None
    )
    assert mine_7 is None, "a 10-day-old order is outside a 7-day window"

    # Widen the window and it comes back — the row was filtered, not lost.
    thirty = await _groups(client, seed, days=30)
    mine_30 = next(
        (g for g in thirty if str(g["outlet_id"]) == seed["outlet_id"]), None
    )
    assert mine_30 is not None, "the same order is inside a 30-day window"


@pytest.mark.asyncio
async def test_route_is_gated_to_super_admin(client, seed):
    # Same gate as every other /admin route. An outlet owner's token is a valid
    # staff JWT — it just is not an admin, which is exactly the case that would
    # leak every restaurant's orders to one restaurant.
    r = await client.get(
        f"{API}/admin/orders/by-restaurant", headers=seed["owner_auth"]
    )
    assert r.status_code in (401, 403), (
        f"owner token must not reach the admin aggregation, got {r.status_code}"
    )

    anon = await client.get(f"{API}/admin/orders/by-restaurant")
    assert anon.status_code in (401, 403)
