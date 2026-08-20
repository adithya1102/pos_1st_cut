"""Orders predating an outlet's rename stay out of the owner app's queue.

Seven demo outlets were re-identified on 2026-08-20 (Spice Route Kitchen ->
Annapoorna Tiffin Room, and six more). 52 of their pre-rename orders were still
in non-terminal statuses, so the owner app opened straight onto a queue of a
stranger's orders.

The fix is a WHERE clause, NOT a delete: every customer_orders row and every
customer_order_items reference survives untouched, and the ADMIN order log still
returns the full history. These tests pin both halves — the hiding AND the
not-deleting — because a future "cleanup" that turns this into a DELETE would
satisfy the first assertion alone.

The cutoff is set per-test rather than taken from the real constant. conftest
disables it suite-wide (RENAME_CUTOFF_ISO=epoch) so no other order test is
coupled to a production date, and pinning both sides of the boundary explicitly
also keeps these tests independent of the naive-utcnow/client-timezone skew that
shifts a locally created order 5h30m into the past.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.modules.carevo_customer.service import CarevoService

API = "/api/v1"

#: Arbitrary but fixed; the tests place orders either side of it.
CUTOFF = datetime(2026, 8, 20, 15, 40, 32, 960232, tzinfo=timezone.utc)


@pytest.fixture
def cutoff(monkeypatch):
    monkeypatch.setattr(CarevoService, "RENAME_CUTOFF", CUTOFF)
    return CUTOFF


async def _queue_ids(client, seed) -> list[str]:
    r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    return [str(o["order_id"]) for o in r.json()]


async def _set_created_at(db, order_id: str, when: datetime) -> None:
    await db.execute(
        text("UPDATE customer_orders SET created_at = :t WHERE id = :i"),
        {"t": when, "i": order_id},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_order_from_before_the_rename_is_hidden_from_the_owner_queue(
    client, seed, paid_order, db, cutoff
):
    order_id = str(paid_order["id"])

    await _set_created_at(db, order_id, cutoff + timedelta(minutes=5))
    assert order_id in await _queue_ids(client, seed), (
        "an order created after the cutoff must start visible"
    )

    # Rewind to one second BEFORE the rename — i.e. make it belong to the
    # outlet's previous identity. Done in SQL, so nothing about the client or
    # the app's clock is involved.
    await _set_created_at(db, order_id, cutoff - timedelta(seconds=1))
    assert order_id not in await _queue_ids(client, seed), (
        "an order created before RENAME_CUTOFF belongs to the outlet's former "
        "identity and must not appear in the new owner's queue"
    )


@pytest.mark.asyncio
async def test_hiding_is_cosmetic_the_row_and_its_items_survive(
    client, seed, paid_order, db, cutoff
):
    order_id = str(paid_order["id"])
    items_before = await db.scalar(
        text("SELECT count(*) FROM customer_order_items WHERE customer_order_id = :i"),
        {"i": order_id},
    )
    assert items_before and items_before > 0

    await _set_created_at(db, order_id, cutoff - timedelta(days=1))
    assert order_id not in await _queue_ids(client, seed)

    # The whole point: hidden, not deleted.
    still_there = await db.scalar(
        text("SELECT count(*) FROM customer_orders WHERE id = :i"), {"i": order_id}
    )
    items_after = await db.scalar(
        text("SELECT count(*) FROM customer_order_items WHERE customer_order_id = :i"),
        {"i": order_id},
    )
    assert still_there == 1, "the filter must never remove the order row"
    assert items_after == items_before, (
        "customer_order_items reference menu_items; dropping them would orphan "
        "real order history"
    )


@pytest.mark.asyncio
async def test_an_order_after_the_cutoff_still_shows(
    client, seed, paid_order, db, cutoff
):
    order_id = str(paid_order["id"])
    await _set_created_at(db, order_id, cutoff + timedelta(seconds=1))
    assert order_id in await _queue_ids(client, seed), (
        "the cutoff is a boundary, not a blanket hide — anything after the "
        "rename is the new restaurant's own history and must be visible"
    )
