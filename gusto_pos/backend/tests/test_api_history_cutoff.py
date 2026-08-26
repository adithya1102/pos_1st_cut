"""A customer's own history can be cut off at an instant, WITHOUT deleting.

Three development accounts had accumulated 61 leftover orders, mostly abandoned
checkouts. Deleting them was attempted and correctly refused by the database:
`order_events` and `prediction_log` carry BEFORE DELETE immutability triggers,
because the prediction engine is event-sourced and those rows are the record.

So `customers.history_cutoff_at` (migration 022) hides them from ONE read —
`GET /customer/orders` — and nothing else. These tests pin both halves, the
hiding AND the not-deleting, because a future "cleanup" that quietly turns this
into a DELETE would satisfy the first alone. That is the same reasoning
test_api_rename_cutoff.py records for the owner-side cutoff, whose shape this
deliberately copies.

Cutoffs are set per-test against seeded orders rather than read from prod, so
nothing here is coupled to the three real account ids or to a production date.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio


async def _history_ids(client, seed) -> list[str]:
    r = await client.get(f"{API}/customer/orders", headers=seed["customer_auth"])
    assert r.status_code == 200, r.text
    return [str(o["order_id"]) for o in r.json()]


async def _set_created_at(db, order_id: str, when: datetime) -> None:
    await db.execute(
        text("UPDATE customer_orders SET created_at = :t WHERE id = :i"),
        {"t": when, "i": order_id},
    )
    await db.commit()


async def _set_cutoff(db, customer_id: str, when: datetime | None) -> None:
    await db.execute(
        text("UPDATE customers SET history_cutoff_at = :t WHERE id = :i"),
        {"t": when, "i": customer_id},
    )
    await db.commit()


async def _order_still_exists(db, order_id: str) -> bool:
    return bool(await db.scalar(
        text("SELECT count(*) FROM customer_orders WHERE id = :i"), {"i": order_id}
    ))


async def test_an_order_before_the_cutoff_is_hidden(client, seed, paid_order, db):
    order_id = str(paid_order["id"])
    assert order_id in await _history_ids(client, seed), "visible before any cutoff"

    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))
    await _set_cutoff(db, seed["customer_id"], now - timedelta(days=1))

    assert order_id not in await _history_ids(client, seed)


async def test_an_order_after_the_cutoff_still_shows(client, seed, paid_order, db):
    """The accounts are still in use — new orders must keep appearing."""
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(minutes=5))
    await _set_cutoff(db, seed["customer_id"], now - timedelta(days=1))

    assert order_id in await _history_ids(client, seed)


async def test_a_null_cutoff_changes_nothing(client, seed, paid_order, db):
    """Every account but the three retired ones has NULL here."""
    order_id = str(paid_order["id"])
    await _set_created_at(db, order_id, datetime(2020, 1, 1, tzinfo=timezone.utc))
    await _set_cutoff(db, seed["customer_id"], None)

    assert order_id in await _history_ids(client, seed), (
        "a NULL cutoff must not hide anything, however old"
    )


async def test_the_hidden_order_is_NOT_deleted(client, seed, paid_order, db):
    """The half a careless 'cleanup' would break.

    Hiding and deleting look identical from the history endpoint. They are not
    the same thing, and for these rows deleting is not even possible.
    """
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))
    await _set_cutoff(db, seed["customer_id"], now)

    assert order_id not in await _history_ids(client, seed)

    assert await _order_still_exists(db, order_id), "the row must survive"
    items = await db.scalar(
        text("SELECT count(*) FROM customer_order_items WHERE customer_order_id = :i"),
        {"i": order_id},
    )
    assert items > 0, "its line items must survive too"


async def test_clearing_the_cutoff_brings_the_history_back(
    client, seed, paid_order, db
):
    """Reversibility, exercised rather than asserted in a comment."""
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))

    await _set_cutoff(db, seed["customer_id"], now)
    assert order_id not in await _history_ids(client, seed)

    await _set_cutoff(db, seed["customer_id"], None)
    assert order_id in await _history_ids(client, seed)


async def test_one_customers_cutoff_does_not_hide_anothers_orders(
    client, seed, paid_order, db
):
    """The cutoff is per-account, not global.

    A global read would have hidden every customer's history the moment the
    three development accounts were retired.
    """
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))

    # A DIFFERENT customer gets a cutoff that would cover this order.
    other = await db.scalar(text(
        "SELECT id FROM customers WHERE id <> :me LIMIT 1"
    ), {"me": seed["customer_id"]})
    if other is None:
        pytest.skip("no second customer in this database")
    await _set_cutoff(db, str(other), now)

    try:
        assert order_id in await _history_ids(client, seed), (
            "another account's cutoff must not touch this one's history"
        )
    finally:
        await _set_cutoff(db, str(other), None)


async def _get_order(client, seed, order_id: str):
    return await client.get(
        f"{API}/customer/orders/{order_id}", headers=seed["customer_auth"]
    )


async def test_a_hidden_order_404s_via_its_direct_id(client, seed, paid_order, db):
    """The list filter alone left a hole: a direct link still returned the
    order in full. Same shape as the cross-outlet verify-pickup gap — the
    filter existed, but only on the path someone happened to look at."""
    order_id = str(paid_order["id"])
    assert (await _get_order(client, seed, order_id)).status_code == 200

    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))
    await _set_cutoff(db, seed["customer_id"], now - timedelta(days=1))

    r = await _get_order(client, seed, order_id)
    assert r.status_code == 404, (
        f"a hidden order must not resolve by direct id — got {r.status_code}"
    )


async def test_the_404_is_indistinguishable_from_no_such_order(
    client, seed, paid_order, db
):
    """403 would confirm the id exists. 404 tells the caller nothing."""
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))
    await _set_cutoff(db, seed["customer_id"], now)

    hidden = await _get_order(client, seed, order_id)
    nonexistent = await _get_order(client, seed, str(uuid.uuid4()))

    assert hidden.status_code == nonexistent.status_code == 404
    assert hidden.json() == nonexistent.json(), (
        "a hidden order must be indistinguishable from one that never existed"
    )


async def test_an_order_after_the_cutoff_still_resolves_by_id(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(minutes=5))
    await _set_cutoff(db, seed["customer_id"], now - timedelta(days=1))

    r = await _get_order(client, seed, order_id)
    assert r.status_code == 200, r.text
    assert str(r.json()["id"]) == order_id


async def test_no_cutoff_means_direct_id_is_unaffected(client, seed, paid_order, db):
    order_id = str(paid_order["id"])
    await _set_created_at(db, order_id, datetime(2020, 1, 1, tzinfo=timezone.utc))
    await _set_cutoff(db, seed["customer_id"], None)

    r = await _get_order(client, seed, order_id)
    assert r.status_code == 200, "a NULL cutoff must hide nothing, however old"


async def test_clearing_the_cutoff_restores_direct_access(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    now = datetime.now(timezone.utc)
    await _set_created_at(db, order_id, now - timedelta(days=7))

    await _set_cutoff(db, seed["customer_id"], now)
    assert (await _get_order(client, seed, order_id)).status_code == 404

    await _set_cutoff(db, seed["customer_id"], None)
    assert (await _get_order(client, seed, order_id)).status_code == 200, (
        "hiding is not deleting — the row is still there and comes straight back"
    )


async def test_the_owner_queue_is_unaffected_by_a_customer_cutoff(
    client, seed, paid_order, db
):
    """owner_app reads its own outlet-scoped query and must not see this at all.

    Staff still have to be able to hand over an order whose customer has cut
    their own history — the two views answer different questions.
    """
    order_id = str(paid_order["id"])
    await _set_cutoff(db, seed["customer_id"], datetime.now(timezone.utc))

    assert order_id not in await _history_ids(client, seed)

    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    assert order_id in [str(o["order_id"]) for o in r.json()], (
        "a customer-side cutoff must never remove an order from the staff queue"
    )
