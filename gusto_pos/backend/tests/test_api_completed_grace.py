"""The owner app's live queue keeps a collected order for 30 minutes.

Before this, verifying a pickup made the order vanish from /pos/orders on the
next refresh — no window to notice a mis-tap, and no way to confirm the right
order had been closed.

The cutoff is computed in SQL from customer_orders.pickup_verified_at, NOT from
a timer in the app. These tests pin that distinction: the second one rewinds the
stored timestamp and expects the row to disappear with no client involved at
all, which is only possible if the server owns the window.

Order history and the admin order log read their own queries and must not be
affected — the last test holds that line.
"""
from __future__ import annotations

import pytest
from datetime import timedelta

from sqlalchemy import text

from app.modules.carevo_customer.service import CarevoService

API = "/api/v1"


async def _verify_pickup(client, seed, order_id: str, db) -> None:
    """Advance an order to COMPLETED through the real staff endpoint."""
    code = await db.scalar(
        text("SELECT pickup_code FROM customer_orders WHERE id = :i"),
        {"i": order_id},
    )
    assert code, "order should have a pickup code once PAID"
    r = await client.post(
        f"{API}/pos/orders/verify-pickup",
        headers=seed["owner_auth"],
        json={"order_id": order_id, "pickup_code": code},
    )
    assert r.status_code == 200, r.text


async def _queue_ids(client, seed) -> list[str]:
    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    return [str(o["order_id"]) for o in r.json()]


@pytest.mark.asyncio
async def test_collected_order_stays_in_the_queue_during_the_grace_window(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    assert order_id in await _queue_ids(client, seed)

    await _verify_pickup(client, seed, order_id, db)

    # Still present: just collected, so well inside the window.
    ids = await _queue_ids(client, seed)
    assert order_id in ids, (
        "a just-collected order must remain visible so staff can see what they "
        "closed"
    )

    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    row = next(o for o in r.json() if str(o["order_id"]) == order_id)
    assert row["status"] == "COMPLETED"
    assert row["pickup_verified_at"] is not None, (
        "the app needs this timestamp to label the row; without it there is "
        "nothing to render but a bare COMPLETED"
    )


@pytest.mark.asyncio
async def test_the_window_closes_on_the_stored_timestamp_not_a_client_timer(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    await _verify_pickup(client, seed, order_id, db)
    assert order_id in await _queue_ids(client, seed)

    # Rewind pickup_verified_at past the cutoff. Nothing client-side changes —
    # no timer is restarted, no app is relaunched. If the row still disappears,
    # the server is the thing enforcing the window, which is the requirement:
    # a client timer would survive this and reset on every app restart.
    minutes = int(CarevoService.COMPLETED_GRACE.total_seconds() // 60) + 1
    await db.execute(
        text(
            "UPDATE customer_orders "
            "SET pickup_verified_at = now() - CAST(:ago AS interval) "
            "WHERE id = :i"
        ),
        # timedelta, not a string: asyncpg maps it to interval directly.
        {"ago": timedelta(minutes=minutes), "i": order_id},
    )
    await db.commit()

    assert order_id not in await _queue_ids(client, seed), (
        f"a pickup verified {minutes} minutes ago is past the "
        f"{CarevoService.COMPLETED_GRACE} window and must drop out"
    )


@pytest.mark.asyncio
async def test_an_aged_out_order_is_still_in_the_customer_s_history(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    await _verify_pickup(client, seed, order_id, db)

    minutes = int(CarevoService.COMPLETED_GRACE.total_seconds() // 60) + 1
    await db.execute(
        text(
            "UPDATE customer_orders "
            "SET pickup_verified_at = now() - CAST(:ago AS interval) "
            "WHERE id = :i"
        ),
        # timedelta, not a string: asyncpg maps it to interval directly.
        {"ago": timedelta(minutes=minutes), "i": order_id},
    )
    await db.commit()

    # Gone from the live queue...
    assert order_id not in await _queue_ids(client, seed)

    # ...but the order itself is untouched. This thins one view, it does not
    # archive or delete anything.
    r = await client.get(f"{API}/customer/orders", headers=seed["customer_auth"])
    assert r.status_code == 200, r.text
    history_ids = [str(o["order_id"]) for o in r.json()]
    assert order_id in history_ids, (
        "the grace window governs the live kitchen queue only — history must "
        "still show every completed order"
    )
