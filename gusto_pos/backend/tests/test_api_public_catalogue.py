"""The /public/* catalogue: open on purpose, and pinned to an exact field set.

The point of this file is the EXACT-KEYS assertions. This router is
unauthenticated by design, so the only thing standing between it and the next
accidental disclosure is the hand-written response model — and a model is only
a boundary while something checks it. `outlets.phone_number` was added by
migration 009 to a table this endpoint reads; a permissive schema would have
published it the day it landed.

So these tests do not assert "the fields I want are present". They assert
"the set of keys is exactly this", which fails on a field APPEARING as loudly
as on one going missing.
"""
import uuid

import pytest

from tests.conftest import API

# Exactly what PublicOutlet serves. Not a subset check.
OUTLET_KEYS = {
    "id", "name", "city", "latitude", "longitude",
    "opens_at", "closes_at", "open_status", "open_reason",
}

# Exactly what PublicMenuItem serves. No description — the column does not
# exist; see the note in app/modules/public/controller.py.
ITEM_KEYS = {"name", "price", "is_veg", "is_available"}

MENU_KEYS = {"outlet_id", "outlet_name", "categories"}

# A category publishes its name and its items — never its id.
CATEGORY_KEYS = {"name", "items"}

# Columns that exist on the rows these endpoints read and must NEVER appear.
FORBIDDEN_OUTLET = {
    "phone_number", "organization_id", "geofence_radius_meters",
    "verification_status", "upi_id", "is_visible", "deactivated_at",
    "locality", "image_url", "created_at",
}
FORBIDDEN_ITEM = {
    "short_code", "tags", "prep_time_minutes", "image_url", "category_id",
    "station", "base_prep_seconds", "occupancy_seconds",
    "hold_tolerance_seconds", "is_batchable", "id",
}


@pytest.mark.asyncio
async def test_outlets_needs_no_credentials(client, seed):
    """Open by design. A 401 here would mean the router was guarded by mistake."""
    r = await client.get(f"{API}/public/outlets")
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_outlet_keys_are_exactly_the_agreed_set(client, seed):
    r = await client.get(f"{API}/public/outlets")
    rows = r.json()
    assert rows, "seed outlet should be listed"
    for row in rows:
        assert set(row) == OUTLET_KEYS, f"unexpected keys: {set(row) ^ OUTLET_KEYS}"
        assert not (set(row) & FORBIDDEN_OUTLET)


@pytest.mark.asyncio
async def test_seeded_outlet_is_present_and_named(client, seed):
    rows = (await client.get(f"{API}/public/outlets")).json()
    mine = [o for o in rows if o["id"] == seed["outlet_id"]]
    assert len(mine) == 1
    # `location_name` is renamed to `name` at the boundary.
    assert mine[0]["name"].startswith("Outlet ")
    assert mine[0]["city"] == "Testville"
    # No hours on the seeded row -> no schedule -> treated as open.
    assert mine[0]["open_status"] == "open"
    assert mine[0]["opens_at"] is None and mine[0]["closes_at"] is None


def _all_items(body: dict) -> list[dict]:
    return [i for c in body["categories"] for i in c["items"]]


@pytest.mark.asyncio
async def test_menu_keys_are_exactly_the_agreed_set(client, seed):
    r = await client.get(f"{API}/public/outlets/{seed['outlet_id']}/menu")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == MENU_KEYS
    assert body["categories"], "seeded category should be served"

    for cat in body["categories"]:
        assert set(cat) == CATEGORY_KEYS, f"unexpected keys: {set(cat) ^ CATEGORY_KEYS}"
        # The category's id must not leak through the grouping.
        assert "id" not in cat and "category_id" not in cat

    items = _all_items(body)
    assert items, "seeded menu item should be served"
    for item in items:
        assert set(item) == ITEM_KEYS, f"unexpected keys: {set(item) ^ ITEM_KEYS}"
        assert not (set(item) & FORBIDDEN_ITEM)


@pytest.mark.asyncio
async def test_item_is_grouped_under_its_own_category(client, seed):
    """The grouping must be real, not a single bucket holding everything.

    The seeded world has one category ('Mains') with one item, so this asserts
    the item arrived under a correctly NAMED section rather than under some
    placeholder the grouping invented.
    """
    body = (await client.get(f"{API}/public/outlets/{seed['outlet_id']}/menu")).json()
    mains = next(c for c in body["categories"] if c["name"] == "Mains")
    assert [i["name"] for i in mains["items"]] == ["Test Dish"]


@pytest.mark.asyncio
async def test_menu_item_values(client, seed):
    body = (await client.get(f"{API}/public/outlets/{seed['outlet_id']}/menu")).json()
    dish = next(i for i in _all_items(body) if i["name"] == "Test Dish")
    assert dish["price"] == 100.0
    assert dish["is_veg"] is True
    assert dish["is_available"] is True


@pytest.mark.asyncio
async def test_no_description_field_is_served(client, seed):
    """Explicit, because `description` was requested and deliberately omitted.

    If someone later adds such a column, this test is where the decision to
    publish it should be made — consciously — rather than inherited.
    """
    body = (await client.get(f"{API}/public/outlets/{seed['outlet_id']}/menu")).json()
    assert all("description" not in i for i in _all_items(body))
    assert all("description" not in c for c in body["categories"])


@pytest.mark.asyncio
async def test_unknown_outlet_404s(client):
    r = await client.get(f"{API}/public/outlets/{uuid.uuid4()}/menu")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_hidden_outlet_is_invisible_and_indistinguishable(client, seed, db):
    """An unlisted outlet must 404 exactly like a nonexistent one.

    Answering 403 would confirm the outlet exists, turning this endpoint into a
    way to enumerate outlets the platform has deliberately hidden.
    """
    from sqlalchemy import text
    await db.execute(text("UPDATE outlets SET is_visible = false WHERE id = :i"),
                     {"i": seed["outlet_id"]})
    await db.commit()

    listed = (await client.get(f"{API}/public/outlets")).json()
    assert seed["outlet_id"] not in [o["id"] for o in listed]

    hidden = await client.get(f"{API}/public/outlets/{seed['outlet_id']}/menu")
    absent = await client.get(f"{API}/public/outlets/{uuid.uuid4()}/menu")
    assert hidden.status_code == absent.status_code == 404
    assert hidden.json() == absent.json()


@pytest.mark.asyncio
async def test_only_get_is_exposed(client, seed):
    """No write verb exists on this router. 405, not 401/403 — the method is
    not registered at all, which is a stronger guarantee than a guard."""
    for verb in ("post", "put", "patch", "delete"):
        r = await getattr(client, verb)(f"{API}/public/outlets")
        assert r.status_code == 405, f"{verb.upper()} -> {r.status_code}"


@pytest.mark.asyncio
async def test_rate_limiter_is_wired_and_per_ip(client, seed, monkeypatch):
    """Trips at the configured cap, and one IP's spend does not affect another.

    The limit is monkeypatched down rather than sending a full quota of real
    requests, so this stays fast and stays correct when the configured cap
    changes — it asserts the limiter's BEHAVIOUR, never a particular number.
    """
    from app.modules.public import service as svc

    monkeypatch.setattr(svc.settings, "PUBLIC_API_RATE_LIMIT_PER_HOUR", 3)
    svc._public_hits.clear()

    hdr = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(3):
        assert (await client.get(f"{API}/public/outlets", headers=hdr)).status_code == 200
    blocked = await client.get(f"{API}/public/outlets", headers=hdr)
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") == "3600"

    # A different IP has its own budget.
    other = await client.get(f"{API}/public/outlets",
                             headers={"X-Forwarded-For": "203.0.113.8"})
    assert other.status_code == 200

    svc._public_hits.clear()
