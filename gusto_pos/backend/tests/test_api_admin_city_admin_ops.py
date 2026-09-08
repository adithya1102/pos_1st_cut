"""Admin-only city creation and rename.

Two capabilities that deliberately do NOT exist on the owner path:

* an admin adds a city that is live immediately (no pending gate — the admin is
  the approval authority, so queueing their entry for their own approval is
  ceremony), and
* an admin renames a city in place.

The rename is the sharp one. **`outlets.city` is a denormalised varchar, not a
FK to `cities.id`** — `outlets` has exactly one foreign key and it is
`organization_id`. Nothing cascades. So renaming the `cities` row alone would
strand every outlet on a spelling that is no longer in the canonical list. The
service rewrites those outlets in the same transaction, and the first rename
test below is what stops that being quietly removed later.

A collision is refused rather than merged: pointing two cities' outlets at one
row relocates real restaurants and cannot be undone by renaming back.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import API


@pytest.fixture(autouse=True)
def _reset_register_rate_limit():
    from app.modules.carevo_customer import service as svc

    svc._register_hits.clear()
    yield
    svc._register_hits.clear()


async def _mk_city(client, seed, name: str):
    return await client.post(
        f"{API}/admin/cities", headers=seed["admin_auth"], json={"name": name}
    )


@pytest.mark.asyncio
async def test_admin_created_city_is_active_immediately_not_pending(client, seed, db):
    name = f"TEST_CAREVO_Adminopolis_{uuid.uuid4().hex[:8]}"
    r = await _mk_city(client, seed, name)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active", (
        "an admin IS the approval authority — their own entry must not be "
        "parked in a queue only they can service"
    )
    assert body["created"] is True

    status = await db.scalar(
        text("SELECT status FROM cities WHERE lower(name) = lower(:n)"), {"n": name}
    )
    assert status == "active"

    # And it is immediately selectable by the public list owner_app reads.
    listed = await client.get(f"{API}/cities")
    assert name.lower() in {c["name"].lower() for c in listed.json()}


@pytest.mark.asyncio
async def test_admin_create_reuses_an_existing_name_case_insensitively(client, seed, db):
    before = await db.scalar(
        text("SELECT count(*) FROM cities WHERE lower(name) = lower('Bengaluru')")
    )
    assert before == 1

    r = await _mk_city(client, seed, "bEnGaLuRu")
    assert r.status_code == 201, r.text
    assert r.json()["created"] is False, "an existing row must be reused, not duplicated"
    assert r.json()["name"] == "Bengaluru", "the canonical spelling is returned"

    after = await db.scalar(
        text("SELECT count(*) FROM cities WHERE lower(name) = lower('Bengaluru')")
    )
    assert after == 1


@pytest.mark.asyncio
async def test_rename_rewrites_every_outlet_holding_the_old_name(client, seed, db):
    """The load-bearing test. outlets.city is a string, so without the explicit
    UPDATE the outlet keeps a name absent from the canonical list."""
    old = f"TEST_CAREVO_Oldname_{uuid.uuid4().hex[:8]}"
    created = (await _mk_city(client, seed, old)).json()

    # Point the seeded outlet at it, the way a real onboarding would.
    await db.execute(
        text("UPDATE outlets SET city = :c WHERE id = :i"),
        {"c": old, "i": seed["outlet_id"]},
    )
    await db.commit()

    new = f"TEST_CAREVO_Newname_{uuid.uuid4().hex[:8]}"
    r = await client.patch(
        f"{API}/admin/cities/{created['id']}",
        headers=seed["admin_auth"],
        json={"name": new},
    )
    assert r.status_code == 200, r.text
    assert r.json()["previous_name"] == old
    assert r.json()["outlets_updated"] >= 1

    outlet_city = await db.scalar(
        text("SELECT city FROM outlets WHERE id = :i"), {"i": seed["outlet_id"]}
    )
    assert outlet_city == new, (
        "outlets.city is denormalised — the rename must carry it, or the outlet "
        "is left on a spelling the canonical list no longer contains"
    )

    stale = await db.scalar(
        text("SELECT count(*) FROM outlets WHERE city = :old"), {"old": old}
    )
    assert stale == 0


@pytest.mark.asyncio
async def test_rename_onto_an_existing_city_is_refused_not_merged(client, seed, db):
    a = f"TEST_CAREVO_CityA_{uuid.uuid4().hex[:8]}"
    b = f"TEST_CAREVO_CityB_{uuid.uuid4().hex[:8]}"
    city_a = (await _mk_city(client, seed, a)).json()
    await _mk_city(client, seed, b)

    # Different case on purpose: the guarantee is case-insensitive.
    r = await client.patch(
        f"{API}/admin/cities/{city_a['id']}",
        headers=seed["admin_auth"],
        json={"name": b.upper()},
    )
    assert r.status_code == 409, r.text
    assert "merge" in r.text.lower(), "the refusal must explain why, not just say no"

    # Neither row moved.
    assert await db.scalar(
        text("SELECT count(*) FROM cities WHERE lower(name) = lower(:n)"), {"n": a}
    ) == 1
    assert await db.scalar(
        text("SELECT count(*) FROM cities WHERE lower(name) = lower(:n)"), {"n": b}
    ) == 1


@pytest.mark.asyncio
async def test_owner_self_service_path_is_still_gated(client, db):
    """The whole point of admin-only creation is that the OWNER path keeps its
    gate. A regression here would let any unauthenticated signup extend the
    canonical list."""
    tag = uuid.uuid4().hex[:8]
    new_city = f"TEST_CAREVO_OwnerAsked_{tag}"
    body = {
        "restaurant_name": f"TEST_CAREVO_Gate_{tag}",
        "requested_city": new_city,
        "locality": "Somewhere",
        "phone_number": "9876500000",
        "email": f"test_carevo_gate_{tag}@example.com",
        "username": f"test_carevo_gate_{tag}",
        "password": "correct-horse-battery",
        "upi_id": "test@upi",
        "latitude": 12.9352,
        "longitude": 77.6245,
    }
    r = await client.post(f"{API}/register", json=body)
    assert r.status_code == 201, r.text

    status = await db.scalar(
        text("SELECT status FROM cities WHERE lower(name) = lower(:n)"), {"n": new_city}
    )
    assert status == "pending", (
        "an owner's requested city must still land pending — admin-side "
        "creation must not have loosened the self-service path"
    )

    listed = await client.get(f"{API}/cities")
    assert new_city.lower() not in {c["name"].lower() for c in listed.json()}


@pytest.mark.asyncio
async def test_city_admin_routes_are_super_admin_only(client, seed):
    """An outlet owner holds a valid staff JWT — it just is not an admin."""
    r = await client.post(
        f"{API}/admin/cities", headers=seed["owner_auth"], json={"name": "Nowhere City"}
    )
    assert r.status_code in (401, 403), r.text

    r = await client.patch(
        f"{API}/admin/cities/{uuid.uuid4()}",
        headers=seed["owner_auth"],
        json={"name": "Nowhere City"},
    )
    assert r.status_code in (401, 403), r.text
