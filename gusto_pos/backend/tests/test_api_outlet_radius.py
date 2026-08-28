"""Radius filtering happens IN the query, not after it.

Before this, `/customer/outlets` applied no distance predicate at all: it
returned every visible outlet from any origin on Earth — verified against prod
at the time, where a Bengaluru origin returned a Kolkata outlet 1566km away —
and `distance_km` was a post-query Python annotation used only to sort.

The annotation stays, because the list still shows and sorts by distance. The
radius is a SECOND thing, in the WHERE clause, and these tests pin that the two
agree: an outlet the filter admits must be one the annotation calls close, and
the boundary must land in the same place for both.

PostGIS is deliberately not used — it is not installed on this database, and
installing an extension on prod for one predicate over seven rows is a worse
trade than writing the haversine out. The SQL mirrors CarevoService
._haversine_km term for term; a drift between them is exactly what
test_the_filter_and_the_shown_distance_agree would catch.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio

#: Bengaluru, the origin every test measures from.
ORIGIN = (12.9716, 77.5946)

#: Roughly 1 degree of latitude ~= 111.19 km, which is all these need: placing
#: an outlet N km due north is a latitude offset and nothing else.
KM_PER_DEG_LAT = 111.194927


def _north_of(origin, km: float) -> tuple[float, float]:
    """A point `km` due north of `origin` — same longitude, so the haversine
    reduces to the latitude difference and the expected distance is exact."""
    return (origin[0] + km / KM_PER_DEG_LAT, origin[1])


async def _make_outlet(db, seed, km_north=None, *, city="Testville",
                       lat=None, lng=None) -> str:
    """A visible outlet, either `km_north` of ORIGIN or at explicit lat/lng.

    Reuses the seed's organization rather than making one — `seed` does not
    expose org_id, so it is read back off the outlet it already created.
    """
    if km_north is not None:
        lat, lng = _north_of(ORIGIN, km_north)
    org = await db.scalar(
        text("SELECT organization_id FROM outlets WHERE id = :i"),
        {"i": seed["outlet_id"]},
    )
    oid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             upi_id, geofence_radius_meters, verification_status,
                             latitude, longitude, created_at)
        VALUES (:i, :o, :n, :c, true, 'test@upi', 150, 'active', :la, :ln, now())
    """), {"i": str(oid), "o": str(org), "n": f"TEST_CAREVO_Radius {oid.hex[:6]}",
           "c": city, "la": lat, "ln": lng})
    await db.commit()
    return str(oid)


async def _ids(client, seed, **params) -> list[str]:
    r = await client.get(f"{API}/customer/outlets", headers=seed["customer_auth"],
                         params=params)
    assert r.status_code == 200, r.text
    return [str(o["id"]) for o in r.json()]


async def _rows(client, seed, **params) -> list[dict]:
    r = await client.get(f"{API}/customer/outlets", headers=seed["customer_auth"],
                         params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
async def near_and_far(db, seed):
    """Four outlets at known distances due north of ORIGIN.

    Placed either side of BOTH boundaries, because a filter that happened to
    admit everything or nothing would pass a one-sided test.
    """
    return {
        "inside_65": await _make_outlet(db, seed, 60),
        "outside_65": await _make_outlet(db, seed, 70),
        "inside_300": await _make_outlet(db, seed, 280),
        "outside_300": await _make_outlet(db, seed, 320),
    }


async def test_65km_admits_inside_and_rejects_outside(client, seed, near_and_far):
    ids = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1], radius_km=65)
    assert near_and_far["inside_65"] in ids, "60km outlet must be inside a 65km radius"
    assert near_and_far["outside_65"] not in ids, "70km outlet must be excluded"
    assert near_and_far["inside_300"] not in ids
    assert near_and_far["outside_300"] not in ids


async def test_300km_admits_inside_and_rejects_outside(client, seed, near_and_far):
    ids = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1], radius_km=300)
    assert near_and_far["inside_65"] in ids
    assert near_and_far["outside_65"] in ids, "70km is inside 300km"
    assert near_and_far["inside_300"] in ids, "280km outlet must be inside 300km"
    assert near_and_far["outside_300"] not in ids, "320km outlet must be excluded"


async def test_no_radius_still_returns_everything(client, seed, near_and_far):
    """The pre-existing behaviour, unchanged when no radius is asked for."""
    ids = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1])
    for k in near_and_far.values():
        assert k in ids, "without a radius, distance must not exclude anything"


async def test_a_radius_without_an_origin_is_ignored(client, seed, near_and_far):
    """A radius with nothing to measure from is not a filter.

    It is dropped rather than guessing an origin or returning an empty list —
    an empty list would read to the customer as "no restaurants near you",
    which would be a claim the server is in no position to make.
    """
    ids = await _ids(client, seed, radius_km=65)
    for k in near_and_far.values():
        assert k in ids


async def test_the_filter_and_the_shown_distance_agree(client, seed, near_and_far):
    """The WHERE clause and the displayed distance_km must not disagree.

    They are two separate implementations of the same haversine — one in SQL,
    one in Python. This is the test that fails if either drifts.
    """
    rows = await _rows(client, seed, lat=ORIGIN[0], lng=ORIGIN[1], radius_km=65)
    for o in rows:
        if o["distance_km"] is not None:
            assert o["distance_km"] <= 65.0 + 1e-6, (
                f'{o["name"]} was admitted by the filter but shows '
                f'{o["distance_km"]}km, outside the 65km asked for'
            )


async def test_an_outlet_with_no_pin_is_excluded_by_a_radius(client, seed, db):
    """Unknowable distance is not the same as zero distance.

    Including it would put an outlet of unknown distance inside a circle the
    customer explicitly drew.
    """
    blind = await _make_outlet(db, seed, lat=None, lng=None)

    with_radius = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1], radius_km=65)
    assert blind not in with_radius

    # ...but it is still listed when no radius is asked for, so it is hidden
    # by the question, not deleted from the world.
    without = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1])
    assert blind in without


async def test_city_filter_works_alone(client, seed, db):
    """Unchanged behaviour — the radius must not have disturbed it."""
    here = await _make_outlet(db, seed, 10, city="Radiusville")
    elsewhere = await _make_outlet(db, seed, 10, city="Otherville")

    ids = await _ids(client, seed, city="Radiusville")
    assert here in ids
    assert elsewhere not in ids


async def test_city_and_radius_are_independent_and_AND_together(client, seed, db):
    """Both at once is a coherent question and the server answers it.

    The app sends only one at a time, but that is the APP's product decision.
    Refusing the combination here would invent a rule the data does not have.
    """
    near_right_city = await _make_outlet(db, seed, 20, city="Radiusville")
    far_right_city = await _make_outlet(db, seed, 400, city="Radiusville")
    near_wrong_city = await _make_outlet(db, seed, 20, city="Otherville")

    ids = await _ids(client, seed, lat=ORIGIN[0], lng=ORIGIN[1],
                     radius_km=65, city="Radiusville")
    assert near_right_city in ids
    assert far_right_city not in ids, "right city, but outside the radius"
    assert near_wrong_city not in ids, "inside the radius, but wrong city"


async def test_a_nonsense_radius_is_refused_not_silently_clamped(client, seed):
    for bad in (0, -5, 20001):
        r = await client.get(f"{API}/customer/outlets", headers=seed["customer_auth"],
                             params={"lat": ORIGIN[0], "lng": ORIGIN[1], "radius_km": bad})
        assert r.status_code == 422, f"radius_km={bad} should be refused, got {r.status_code}"
