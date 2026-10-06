"""Legacy POST /api/v1/orders/ and PUT /api/v1/orders/{id} — server-side pricing.

WHAT WAS WRONG
--------------
OrderItemCreate was `{name, quantity, unit_price}` with NO menu_item_id, so
there was nothing on the server to price against — the money came off the wire
and was stored verbatim. OrderCreate additionally REQUIRED a client-supplied
`total_amount`, which was never cross-checked against the lines.

Verified against a live server before this change:

    POST /api/v1/orders/            (no Authorization header)
    {"outlet_id": "...", "table_id": "pricetest1", "total_amount": 0.01,
     "items":[{"name":"Chicken Biryani","quantity":5,"unit_price":0.002}]}
    -> 201 Created
       DB: orders.total_amount = 0.01, order_items.price_snap = 0.00

Now `menu_item_id` is required, the price and the stored name come from
menu_items, `total_amount` is rejected as an unknown field on both the create
and the update, and the order total is computed.

NOTE ON AUTH: these routes remain UNAUTHENTICATED — that is unchanged and out
of scope here. The point of this change is that an anonymous caller can no
longer choose the price, not that they can no longer reach the endpoint.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from tests.conftest import API

ORDERS = f"{API}/orders/"


async def _item_price(db, item_id) -> float:
    return float(await db.scalar(
        text("SELECT base_price FROM menu_items WHERE id = :i"), {"i": str(item_id)}))


# --------------------------- the exploit, closed ------------------------------

@pytest.mark.asyncio
async def test_declared_unit_price_is_ignored(client, seed, db):
    """The old attack payload shape no longer sets the price.

    unit_price is not a field any more, so sending it is a 422 (extra fields
    are forbidden) rather than silently honoured.
    """
    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": "T_PRICE_1",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 5,
                   "unit_price": 0.002}],
    })
    assert r.status_code == 422, (
        f"unit_price was accepted: {r.status_code} {r.text}")


@pytest.mark.asyncio
async def test_total_amount_is_rejected_on_create(client, seed):
    """It used to be REQUIRED; now sending it is refused outright.

    Refused rather than ignored on purpose — accepting and discarding it would
    leave the caller believing it had set the price.
    """
    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": "T_PRICE_2",
        "total_amount": 0.01,
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_price_comes_from_the_menu_row(client, seed, db):
    """The happy path: total == menu base_price x quantity, server-computed."""
    price = await _item_price(db, seed["menu_item_id"])
    qty = 3

    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": f"T_{uuid.uuid4().hex[:6].upper()}",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": qty}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total_amount"] == pytest.approx(price * qty)

    stored = await db.scalar(
        text("SELECT total_amount FROM orders WHERE id = :i"), {"i": body["id"]})
    assert float(stored) == pytest.approx(price * qty)

    line = (await db.execute(text(
        "SELECT name_snap, price_snap, quantity FROM order_items "
        "WHERE order_id = :i"), {"i": body["id"]})).first()
    assert float(line.price_snap) == pytest.approx(price)
    assert line.quantity == qty


@pytest.mark.asyncio
async def test_name_snap_comes_from_the_menu_not_the_request(client, seed, db):
    """A caller cannot relabel what they bought."""
    real_name = await db.scalar(
        text("SELECT name FROM menu_items WHERE id = :i"),
        {"i": seed["menu_item_id"]})

    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": f"T_{uuid.uuid4().hex[:6].upper()}",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1,
                   "name": "Free Water"}],
    })
    assert r.status_code == 201, r.text

    stored_name = await db.scalar(text(
        "SELECT name_snap FROM order_items WHERE order_id = :i"),
        {"i": r.json()["id"]})
    assert stored_name == real_name, (
        f"stored the client's label {stored_name!r} instead of {real_name!r}")


# ------------------------------ required field --------------------------------

@pytest.mark.asyncio
async def test_menu_item_id_is_required(client, seed):
    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": "T_PRICE_3",
        "items": [{"name": "Chicken Biryani", "quantity": 1}],
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_unknown_menu_item_is_400_not_500(client, seed):
    """A deliberate answer, not an opaque correlation-id 500.

    _fail() wraps every exception into a 500; it now lets HTTPException pass
    through so this stays actionable.
    """
    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": "T_PRICE_4",
        "items": [{"menu_item_id": "00000000-0000-0000-0000-000000000000",
                   "quantity": 1}],
    })
    assert r.status_code == 400, r.text
    assert "Unknown menu item" in r.text


@pytest.mark.asyncio
async def test_inactive_item_is_409(client, seed, db):
    await db.execute(text("UPDATE menu_items SET is_active = false WHERE id = :i"),
                     {"i": seed["menu_item_id"]})
    await db.commit()
    try:
        r = await client.post(ORDERS, json={
            "outlet_id": seed["outlet_id"],
            "table_id": "T_PRICE_5",
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
        })
        assert r.status_code == 409, r.text
    finally:
        await db.execute(
            text("UPDATE menu_items SET is_active = true WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()


@pytest.mark.asyncio
async def test_zero_quantity_is_rejected(client, seed):
    r = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": "T_PRICE_6",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 0}],
    })
    assert r.status_code == 422, r.text


# ------------------------------- the update path ------------------------------

@pytest.mark.asyncio
async def test_total_amount_is_rejected_on_update(client, seed, db):
    """Closing POST alone would be pointless: create honestly, then overwrite."""
    created = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": f"T_{uuid.uuid4().hex[:6].upper()}",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
    })
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    honest_total = created.json()["total_amount"]

    r = await client.put(f"{API}/orders/{oid}", json={"total_amount": 0.01})
    assert r.status_code == 422, (
        f"an arbitrary total was accepted on update: {r.status_code} {r.text}")

    still = await db.scalar(
        text("SELECT total_amount FROM orders WHERE id = :i"), {"i": oid})
    assert float(still) == pytest.approx(honest_total)


@pytest.mark.asyncio
async def test_replace_items_reprices_server_side(client, seed, db):
    """PUT /orders/{id}/items recomputes from the menu, not from the payload."""
    price = await _item_price(db, seed["menu_item_id"])
    created = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": f"T_{uuid.uuid4().hex[:6].upper()}",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
    })
    assert created.status_code == 201, created.text
    oid = created.json()["id"]

    r = await client.put(f"{API}/orders/{oid}/items",
                         headers=seed["owner_auth"],
                         json={"items": [{"menu_item_id": seed["menu_item_id"],
                                          "quantity": 4}]})
    assert r.status_code == 200, r.text
    assert r.json()["total_amount"] == pytest.approx(price * 4)


@pytest.mark.asyncio
async def test_a_bad_replace_payload_leaves_the_existing_lines_alone(
        client, seed, db):
    """Prices are resolved BEFORE the delete, so a failure is not destructive."""
    created = await client.post(ORDERS, json={
        "outlet_id": seed["outlet_id"],
        "table_id": f"T_{uuid.uuid4().hex[:6].upper()}",
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
    })
    oid = created.json()["id"]

    r = await client.put(f"{API}/orders/{oid}/items",
                         headers=seed["owner_auth"],
                         json={"items": [
                             {"menu_item_id": "00000000-0000-0000-0000-000000000000",
                              "quantity": 1}]})
    assert r.status_code == 400, r.text

    remaining = await db.scalar(text(
        "SELECT count(*) FROM order_items WHERE order_id = :i"), {"i": oid})
    assert remaining == 1, "the existing lines were wiped by a failed replace"
