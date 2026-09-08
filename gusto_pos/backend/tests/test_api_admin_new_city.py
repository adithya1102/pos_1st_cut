"""New-city requests from the admin onboarding form.

admin_app's onboarding form previously offered ONLY a dropdown of already-active
cities, so an admin onboarding a restaurant in a city the platform had never
seen had no way through — while owner_app's self-signup had carried a
"request a new city" path since migration 013. Both forms post to the same
`/register`, so the capability already existed server-side and only the admin UI
was missing it.

These tests pin the server side of that shared contract: the request creates a
PENDING city (not an active one), the case-insensitive uniqueness guarantee
holds, and picking an existing city still works unchanged.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import API


@pytest.fixture(autouse=True)
def _reset_register_rate_limit():
    """/register is capped at 5/hour per IP by an in-process dict, and these
    tests share one process and one client IP."""
    from app.modules.carevo_customer import service as svc

    svc._register_hits.clear()
    yield
    svc._register_hits.clear()


def _payload(tag: str, **over):
    body = {
        "restaurant_name": f"TEST_CAREVO_City_{tag}",
        "city": "Bengaluru",
        "locality": "Koramangala",
        "phone_number": "9876500000",
        "email": f"test_carevo_city_{tag}@example.com",
        "username": f"test_carevo_city_{tag}",
        "password": "correct-horse-battery",
        "upi_id": "test@upi",
        "latitude": 12.9352,
        "longitude": 77.6245,
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_requested_city_creates_a_pending_row_not_an_active_one(client, db):
    tag = uuid.uuid4().hex[:8]
    new_city = f"TEST_CAREVO_Metropolis_{tag}"

    body = _payload(tag, requested_city=new_city)
    body.pop("city")                      # exactly one of the two
    r = await client.post(f"{API}/register", json=body)
    assert r.status_code == 201, r.text

    row = (await db.execute(text(
        "SELECT name, status, requested_by_outlet_id FROM cities "
        "WHERE lower(name) = lower(:n)"
    ), {"n": new_city})).first()
    assert row is not None, "the request must land in the cities table"
    assert row.status == "pending", (
        "a requested city must NOT go live on an admin's say-so — it rides the "
        "same approve/reject queue as outlet verification"
    )
    assert row.requested_by_outlet_id is not None, (
        "the admin queue needs to know which outlet asked"
    )

    # The outlet carries the name immediately, so onboarding is not blocked
    # while the city waits for approval.
    outlet_city = await db.scalar(text(
        "SELECT city FROM outlets WHERE id = :i"), {"i": str(row.requested_by_outlet_id)})
    assert outlet_city == new_city

    # And it must not be selectable by anyone else yet.
    listed = await client.get(f"{API}/cities")
    assert listed.status_code == 200, listed.text
    names = {c["name"].lower() for c in listed.json()}
    assert new_city.lower() not in names, (
        "/cities returns active cities only; a pending request must stay "
        "invisible until approved"
    )


@pytest.mark.asyncio
async def test_requesting_an_existing_city_does_not_duplicate_it(client, db):
    """Case-insensitive, which is the guarantee cities.lower(name) makes."""
    before = await db.scalar(text(
        "SELECT count(*) FROM cities WHERE lower(name) = lower('Bengaluru')"))
    assert before == 1

    tag = uuid.uuid4().hex[:8]
    body = _payload(tag, requested_city="bEnGaLuRu")   # same city, different case
    body.pop("city")
    r = await client.post(f"{API}/register", json=body)
    assert r.status_code == 201, r.text

    after = await db.scalar(text(
        "SELECT count(*) FROM cities WHERE lower(name) = lower('Bengaluru')"))
    assert after == 1, (
        "a differently-cased duplicate must not create a second row — this is "
        "exactly the Bangalore/Bengaluru split the cities table exists to stop"
    )
    still_active = await db.scalar(text(
        "SELECT status FROM cities WHERE lower(name) = lower('Bengaluru')"))
    assert still_active == "active", (
        "an existing ACTIVE city must never be knocked back to pending by "
        "someone re-requesting it"
    )


@pytest.mark.asyncio
async def test_choosing_an_existing_city_from_the_dropdown_still_works(client, db):
    """The path admin_app already had must be unaffected by adding the new one."""
    tag = uuid.uuid4().hex[:8]
    r = await client.post(f"{API}/register", json=_payload(tag, city="Bengaluru"))
    assert r.status_code == 201, r.text
    outlet_id = r.json()["outlet_id"]

    city = await db.scalar(text("SELECT city FROM outlets WHERE id = :i"),
                           {"i": str(outlet_id)})
    assert city == "Bengaluru", "canonical spelling is stored, not the submitted casing"


@pytest.mark.asyncio
async def test_both_or_neither_city_is_refused(client):
    """_exactly_one_city — the ambiguity is rejected rather than resolved by
    silently preferring one, because the two paths behave differently."""
    tag = uuid.uuid4().hex[:8]

    both = _payload(tag, city="Bengaluru", requested_city="Someplace")
    r = await client.post(f"{API}/register", json=both)
    assert r.status_code == 422, r.text

    neither = _payload(f"{tag}b")
    neither.pop("city")
    r = await client.post(f"{API}/register", json=neither)
    assert r.status_code == 422, r.text
