"""POST /api/v1/customer/orders/{id}/advance — outlet scoping.

The endpoint declared `_staff=Depends(get_current_staff)` and never read the
result, while CarevoService.advance_status filtered on the order id alone:

    res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))

So the request was authenticated but not AUTHORISED. Any staff account at any
outlet could drive any order in the system — including advancing another
restaurant's order to READY, which fires that customer's "your order is ready"
push and starts their pickup TTL.

A cross-outlet id answers 404, not 403, matching /pos/orders/lookup-pickup:
"exists but belongs to another outlet" is itself information about another
outlet's orders.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash
from tests.conftest import API


async def _second_outlet_staff(db, seed) -> dict:
    """A staff user at a DIFFERENT outlet in the same organisation."""
    org_id = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})

    other_outlet = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO outlets (id, location_name, city, organization_id,
                             geofence_radius_meters, verification_status,
                             is_visible, relocation_is_pending,
                             is_manually_closed, created_at)
        VALUES (:i, 'TEST_CAREVO_other_outlet', 'Bengaluru', :org,
                500, 'active', true, false, false, now())
    """), {"i": str(other_outlet), "org": str(org_id)})

    uname = f"TEST_CAREVO_other_staff_{uuid.uuid4().hex[:8]}"
    uid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, :h, true, :o, now())
    """), {"i": str(uid), "u": uname, "h": get_password_hash("correct-horse"),
           "o": str(other_outlet)})
    await db.commit()
    return {
        "outlet_id": str(other_outlet),
        "user_id": str(uid),
        "auth": {"Authorization": f"Bearer {create_access_token(subject=uname)}"},
    }


@pytest.mark.asyncio
async def test_cross_outlet_staff_cannot_advance(client, seed, paid_order, db):
    """THE REGRESSION THIS FILE EXISTS FOR.

    A staff token from outlet B must not move an order belonging to outlet A,
    and the order's status must be unchanged afterwards.
    """
    other = await _second_outlet_staff(db, seed)
    order_id = paid_order['id']

    before = await db.scalar(
        text("SELECT status FROM customer_orders WHERE id = :i"), {"i": order_id})

    r = await client.post(f"{API}/customer/orders/{order_id}/advance",
                          json={"status": "READY"}, headers=other["auth"])
    assert r.status_code == 404, (
        f"cross-outlet staff advanced another outlet's order: "
        f"{r.status_code} {r.text}"
    )

    after = await db.scalar(
        text("SELECT status FROM customer_orders WHERE id = :i"), {"i": order_id})
    assert after == before, f"status moved {before} -> {after} despite the refusal"


@pytest.mark.asyncio
async def test_own_outlet_staff_can_still_advance(client, seed, paid_order, db):
    """The guard must not break the legitimate path."""
    order_id = paid_order['id']
    r = await client.post(f"{API}/customer/orders/{order_id}/advance",
                          json={"status": "PREPARING"},
                          headers=seed["owner_auth"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PREPARING"


@pytest.mark.asyncio
async def test_staff_with_no_outlet_is_403(client, db, paid_order):
    """An account with outlet_id NULL has no outlet to scope to.

    403 rather than 404 here: this is a statement about the CALLER, not about
    whether the order exists, and it is the same answer /pos/* gives via
    _require_outlet.
    """
    uname = f"TEST_CAREVO_no_outlet_{uuid.uuid4().hex[:8]}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, created_at)
        VALUES (:i, :u, :h, true, now())
    """), {"i": str(uuid.uuid4()), "u": uname,
           "h": get_password_hash("correct-horse")})
    await db.commit()

    hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}
    r = await client.post(
        f"{API}/customer/orders/{paid_order['id']}/advance",
        json={"status": "READY"}, headers=hdr)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_anonymous_is_still_401(client, paid_order):
    r = await client.post(
        f"{API}/customer/orders/{paid_order['id']}/advance",
        json={"status": "READY"})
    assert r.status_code == 401, r.text
