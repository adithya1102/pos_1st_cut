"""Meal-time slots (migration 043).

Three routes under /pos, and the whole of what they are allowed to do:
  * GET  /pos/meal-slots              — all four keys, saved or not;
  * PUT  /pos/meal-slots/{key}        — owner/manager only, replaces the dish
    set, and refuses a foreign id without writing anything;
  * POST /pos/meal-slots/{key}/apply  — any outlet staff, one transaction,
    idempotent, never turns on a dish that is tracked and at zero, and refuses
    an empty slot rather than turning the entire menu off.

THE ASSERTIONS THAT MATTER MOST
-------------------------------
1. `TestForeignItemRejected` — a slot is the owner's statement of what the
   restaurant sells at a part of the day. If a foreign id could be half-saved,
   the slot would differ from the one they ticked and `apply` would then write
   availability from it.

2. `TestApplySkipsOutOfStock` — `is_available = false` on a dish tracked at
   zero was written by the stock path and means "there are none". A menu
   switch overruling that would offer a dish the kitchen cannot make.

3. `TestCrossOutlet` — both UPDATEs in `apply` are scoped through
   menu_items -> categories -> menus -> outlet, so one restaurant tapping a
   slot can never alter another's menu.

4. `TestEmptySlot` — applying the empty set is the one destructive reading of
   this feature ("turn everything off"), so it is a 422 and not a no-op.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash

API = "/api/v1"
SLOTS = f"{API}/pos/meal-slots"
KEYS = ("morning", "afternoon", "evening", "night")


# ------------------------------- helpers ------------------------------------
async def _add_item(db, seed, name, *, available=True, stock=None, active=True):
    """One more dish on the seed outlet's existing category.

    Returns its id as a string. `stock=None` is UNTRACKED, which is what every
    dish is until a restaurant sets a number.
    """
    iid = uuid.uuid4()
    cat_id = await db.scalar(text("""
        SELECT c.id FROM categories c
          JOIN menus m ON m.id = c.menu_id
         WHERE m.outlet_id = :o LIMIT 1
    """), {"o": seed["outlet_id"]})
    await db.execute(text("""
        INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                is_active, is_available, stock_remaining,
                                created_at)
        VALUES (:i, :c, :n, 100, true, :act, :av, :st, now())
    """), {"i": str(iid), "c": str(cat_id), "n": name, "av": available,
           "st": stock, "act": active})
    await db.commit()
    return str(iid)


async def _staff(db, outlet_id, role_name=None, *, owner_flag=False):
    """A staff account at `outlet_id`, optionally with one role.

    Mirrors the helper in test_api_settings_escalation.py. `owner_flag=False`
    by default here because the interesting case for this suite is the
    UNPRIVILEGED account — the one that may apply a slot but not redefine one.
    """
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    username = f"{(role_name or 'norole').lower()}_{tag}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           is_outlet_owner, created_at)
        VALUES (:i, :u, :h, true, :o, :f, now())
    """), {"i": str(uid), "u": username, "f": owner_flag,
           "h": get_password_hash("correct-horse"), "o": str(outlet_id)})
    if role_name:
        rid = await db.scalar(text("SELECT id FROM roles WHERE name = :n"),
                              {"n": role_name})
        if rid is None:
            rid = await db.scalar(text(
                "INSERT INTO roles (name, permissions, created_at) "
                "VALUES (:n, '{}'::jsonb, now()) RETURNING id"), {"n": role_name})
        await db.execute(text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) "
            "ON CONFLICT DO NOTHING"), {"u": str(uid), "r": rid})
    await db.commit()
    return {
        "id": str(uid),
        "auth": {"Authorization":
                 f"Bearer {create_access_token(subject=username)}"},
    }


async def _second_outlet(db):
    """A whole other restaurant: org, outlet, menu, category, one dish, owner."""
    tag = uuid.uuid4().hex[:8]
    org, oid = uuid.uuid4(), uuid.uuid4()
    menu, cat, item, uid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(text(
        "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
        {"i": str(org), "n": f"OrgB {tag}"})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             geofence_radius_meters, verification_status, created_at)
        VALUES (:i,:o,:n,'Testville', true, 150, 'active', now())
    """), {"i": str(oid), "o": str(org), "n": f"OutletB {tag}"})
    await db.execute(text("""
        INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at)
        VALUES (:i,:o,'v1', true, now())"""), {"i": str(menu), "o": str(oid)})
    await db.execute(text("""
        INSERT INTO categories (id, menu_id, name, created_at)
        VALUES (:i,:m,'Mains', now())"""), {"i": str(cat), "m": str(menu)})
    await db.execute(text("""
        INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                is_active, is_available, created_at)
        VALUES (:i,:c,'B Dish', 100, true, true, true, now())
    """), {"i": str(item), "c": str(cat)})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           is_outlet_owner, created_at)
        VALUES (:i,:u,:h, true, :o, true, now())
    """), {"i": str(uid), "u": f"ownerb_{tag}",
           "h": get_password_hash("correct-horse"), "o": str(oid)})
    await db.commit()
    return {
        "outlet_id": str(oid),
        "menu_item_id": str(item),
        "auth": {"Authorization":
                 f"Bearer {create_access_token(subject=f'ownerb_{tag}')}"},
    }


async def _availability(db, outlet_id) -> dict:
    """{menu_item_id: is_available} for every active dish of the outlet."""
    rows = (await db.execute(text("""
        SELECT mi.id, mi.is_available
          FROM menu_items mi
          JOIN categories c ON c.id = mi.category_id
          JOIN menus m ON m.id = c.menu_id
         WHERE m.outlet_id = :o AND mi.is_active = true
    """), {"o": str(outlet_id)})).fetchall()
    return {str(r.id): bool(r.is_available) for r in rows}


async def _put(client, seed, key, item_ids, start=None, end=None, auth=None):
    return await client.put(
        f"{SLOTS}/{key}", headers=auth or seed["owner_auth"],
        json={"start_time": start, "end_time": end, "item_ids": item_ids})


# ============================== GET / PUT ====================================
@pytest.mark.asyncio
class TestRoundtrip:
    async def test_get_returns_all_four_keys_when_nothing_is_saved(
            self, client, seed):
        """Four chips render before the owner has configured anything."""
        r = await client.get(SLOTS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert [s["slot_key"] for s in body] == list(KEYS)
        for s in body:
            assert s["start_time"] is None
            assert s["end_time"] is None
            assert s["item_ids"] == [], "an unsaved slot must read as empty"

    async def test_set_then_get_roundtrips(self, client, seed, db):
        second = await _add_item(db, seed, "Idli")
        r = await _put(client, seed, "morning",
                       [seed["menu_item_id"], second], "07:00", "11:00")
        assert r.status_code == 200, r.text
        assert r.json()["slot_key"] == "morning"
        assert r.json()["start_time"] == "07:00"
        assert r.json()["end_time"] == "11:00"
        assert set(r.json()["item_ids"]) == {seed["menu_item_id"], second}

        g = await client.get(SLOTS, headers=seed["owner_auth"])
        morning = next(s for s in g.json() if s["slot_key"] == "morning")
        assert set(morning["item_ids"]) == {seed["menu_item_id"], second}
        # The other three are untouched by saving one.
        for s in g.json():
            if s["slot_key"] != "morning":
                assert s["item_ids"] == []

    async def test_a_second_save_replaces_rather_than_appends(
            self, client, seed, db):
        a = await _add_item(db, seed, "Dosa")
        b = await _add_item(db, seed, "Vada")
        await _put(client, seed, "evening", [a, b])
        r = await _put(client, seed, "evening", [b])
        assert r.status_code == 200, r.text
        assert r.json()["item_ids"] == [b], "item_ids is a replacement, not a delta"
        # And exactly one slot row exists for the pair, not two.
        n = await db.scalar(text(
            "SELECT count(*) FROM outlet_meal_slots "
            "WHERE outlet_id = :o AND slot_key = 'evening'"),
            {"o": seed["outlet_id"]})
        assert n == 1

    async def test_a_dish_may_be_in_several_slots(self, client, seed, db):
        """The reason membership is a table and not a column on menu_items."""
        lassi = await _add_item(db, seed, "Lassi")
        assert (await _put(client, seed, "morning", [lassi])).status_code == 200
        assert (await _put(client, seed, "night", [lassi])).status_code == 200
        g = await client.get(SLOTS, headers=seed["owner_auth"])
        by_key = {s["slot_key"]: s for s in g.json()}
        assert by_key["morning"]["item_ids"] == [lassi]
        assert by_key["night"]["item_ids"] == [lassi]

    async def test_duplicate_ids_are_collapsed_not_rejected(
            self, client, seed):
        r = await _put(client, seed, "morning",
                       [seed["menu_item_id"], seed["menu_item_id"]])
        assert r.status_code == 200, r.text
        assert r.json()["item_ids"] == [seed["menu_item_id"]]

    async def test_times_are_optional(self, client, seed):
        r = await _put(client, seed, "night", [seed["menu_item_id"]])
        assert r.status_code == 200, r.text
        assert r.json()["start_time"] is None
        assert r.json()["end_time"] is None

    async def test_an_empty_item_list_is_a_valid_save(self, client, seed):
        """Clearing a slot is allowed. APPLYING the result is what is refused."""
        await _put(client, seed, "morning", [seed["menu_item_id"]])
        r = await _put(client, seed, "morning", [])
        assert r.status_code == 200, r.text
        assert r.json()["item_ids"] == []

    @pytest.mark.parametrize("key", list(KEYS))
    async def test_every_legal_key_is_accepted(self, client, seed, key):
        r = await _put(client, seed, key, [seed["menu_item_id"]])
        assert r.status_code == 200, r.text

    # The empty string is deliberately NOT in this list. It makes the URL
    # "/pos/meal-slots/", which Starlette 307-redirects to the collection
    # route — a different endpoint, not an invalid slot key, so asserting a
    # 422 there would be testing the router's trailing-slash behaviour.
    @pytest.mark.parametrize("key", ["brunch", "MORNING_", "late-night", "1"])
    async def test_an_illegal_key_is_422(self, client, seed, key):
        r = await _put(client, seed, key, [seed["menu_item_id"]])
        assert r.status_code == 422, r.text
        n = await client.get(SLOTS, headers=seed["owner_auth"])
        assert all(s["item_ids"] == [] for s in n.json()), \
            "a rejected key must not have written a slot"

    async def test_a_bad_time_is_422(self, client, seed):
        r = await _put(client, seed, "morning", [seed["menu_item_id"]],
                       start="25:00")
        assert r.status_code == 422, r.text


@pytest.mark.asyncio
class TestForeignItemRejected:
    async def test_an_unknown_id_is_404_and_writes_nothing(
            self, client, seed, db):
        ghost = str(uuid.uuid4())
        r = await _put(client, seed, "morning", [seed["menu_item_id"], ghost])
        assert r.status_code == 404, r.text
        assert await db.scalar(text(
            "SELECT count(*) FROM outlet_meal_slots WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]}) == 0, \
            "the whole request must fail — no slot row, not even a partial one"

    async def test_another_outlets_dish_is_404_and_writes_nothing(
            self, client, seed, db):
        other = await _second_outlet(db)
        r = await _put(client, seed, "morning",
                       [seed["menu_item_id"], other["menu_item_id"]])
        assert r.status_code == 404, r.text
        assert await db.scalar(text(
            "SELECT count(*) FROM meal_slot_items"
        )) == 0 or await db.scalar(text("""
            SELECT count(*) FROM meal_slot_items i
              JOIN outlet_meal_slots s ON s.id = i.slot_id
             WHERE s.outlet_id = :o"""), {"o": seed["outlet_id"]}) == 0

    async def test_a_foreign_id_does_not_clobber_an_existing_slot(
            self, client, seed, db):
        """The refusal must leave the previous dish set intact."""
        keep = await _add_item(db, seed, "Keep Me")
        await _put(client, seed, "morning", [keep])
        other = await _second_outlet(db)
        r = await _put(client, seed, "morning", [other["menu_item_id"]])
        assert r.status_code == 404, r.text
        g = await client.get(SLOTS, headers=seed["owner_auth"])
        morning = next(s for s in g.json() if s["slot_key"] == "morning")
        assert morning["item_ids"] == [keep], \
            "a rejected save must not have emptied the slot"


@pytest.mark.asyncio
class TestRoleGate:
    """PUT is owner/manager. GET and apply are not."""

    async def test_anonymous_is_401(self, client, seed):
        assert (await client.get(SLOTS)).status_code in (401, 403)
        assert (await client.put(f"{SLOTS}/morning",
                                 json={"item_ids": []})).status_code in (401, 403)
        assert (await client.post(
            f"{SLOTS}/morning/apply")).status_code in (401, 403)

    async def test_a_customer_token_is_refused(self, client, seed):
        for call in (
            client.get(SLOTS, headers=seed["customer_auth"]),
            client.post(f"{SLOTS}/morning/apply", headers=seed["customer_auth"]),
        ):
            assert (await call).status_code in (401, 403)

    @pytest.mark.parametrize("role", ["Waiter", "Kitchen"])
    async def test_a_non_owner_cannot_define_a_slot(
            self, client, seed, db, role):
        who = await _staff(db, seed["outlet_id"], role)
        r = await _put(client, seed, "morning", [seed["menu_item_id"]],
                       auth=who["auth"])
        assert r.status_code == 403, r.text
        assert await db.scalar(text(
            "SELECT count(*) FROM outlet_meal_slots WHERE outlet_id = :o"),
            {"o": seed["outlet_id"]}) == 0

    async def test_a_role_less_unflagged_account_cannot_define_a_slot(
            self, client, seed, db):
        who = await _staff(db, seed["outlet_id"], None, owner_flag=False)
        r = await _put(client, seed, "morning", [seed["menu_item_id"]],
                       auth=who["auth"])
        assert r.status_code == 403, r.text

    @pytest.mark.parametrize("role", ["Owner", "Manager", "Admin"])
    async def test_privileged_roles_may_define_a_slot(
            self, client, seed, db, role):
        who = await _staff(db, seed["outlet_id"], role)
        r = await _put(client, seed, "morning", [seed["menu_item_id"]],
                       auth=who["auth"])
        assert r.status_code == 200, r.text

    async def test_any_outlet_staff_may_apply(self, client, seed, db):
        """Switching the menu at opening time cannot require the owner's phone."""
        await _put(client, seed, "morning", [seed["menu_item_id"]])
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        r = await client.post(f"{SLOTS}/morning/apply", headers=waiter["auth"])
        assert r.status_code == 200, r.text

    async def test_any_outlet_staff_may_read(self, client, seed, db):
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        r = await client.get(SLOTS, headers=waiter["auth"])
        assert r.status_code == 200, r.text


# ================================ APPLY ======================================
@pytest.mark.asyncio
class TestApply:
    async def test_apply_turns_the_slot_on_and_everything_else_off(
            self, client, seed, db):
        inslot = await _add_item(db, seed, "Breakfast Dish", available=False)
        out1 = await _add_item(db, seed, "Dinner Dish", available=True)
        out2 = await _add_item(db, seed, "Late Dish", available=True)
        await _put(client, seed, "morning", [inslot])

        r = await client.post(f"{SLOTS}/morning/apply",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["slot_key"] == "morning"
        assert body["turned_on"] == 1
        # The seed dish starts available too, so three were on and go off.
        assert body["turned_off"] == 3
        assert body["skipped_out_of_stock"] == 0

        avail = await _availability(db, seed["outlet_id"])
        assert avail[inslot] is True
        assert avail[out1] is False
        assert avail[out2] is False
        assert avail[seed["menu_item_id"]] is False

    async def test_apply_is_idempotent(self, client, seed, db):
        inslot = await _add_item(db, seed, "Only This", available=False)
        await _put(client, seed, "morning", [inslot])

        first = (await client.post(f"{SLOTS}/morning/apply",
                                   headers=seed["owner_auth"])).json()
        state_after_first = await _availability(db, seed["outlet_id"])

        second = (await client.post(f"{SLOTS}/morning/apply",
                                    headers=seed["owner_auth"])).json()
        state_after_second = await _availability(db, seed["outlet_id"])

        assert first["turned_on"] == 1
        assert second["turned_on"] == 0, "nothing left to turn on"
        assert second["turned_off"] == 0, "nothing left to turn off"
        assert state_after_second == state_after_first, \
            "a second apply must leave the menu byte-identical"

    async def test_switching_between_two_slots_both_ways(self, client, seed, db):
        a = await _add_item(db, seed, "Morning Only")
        b = await _add_item(db, seed, "Night Only")
        await _put(client, seed, "morning", [a])
        await _put(client, seed, "night", [b])

        await client.post(f"{SLOTS}/morning/apply", headers=seed["owner_auth"])
        avail = await _availability(db, seed["outlet_id"])
        assert avail[a] is True and avail[b] is False

        await client.post(f"{SLOTS}/night/apply", headers=seed["owner_auth"])
        avail = await _availability(db, seed["outlet_id"])
        assert avail[a] is False and avail[b] is True

    async def test_a_dish_in_both_slots_stays_on_across_a_switch(
            self, client, seed, db):
        shared = await _add_item(db, seed, "Chai")
        only_morning = await _add_item(db, seed, "Poha")
        await _put(client, seed, "morning", [shared, only_morning])
        await _put(client, seed, "night", [shared])

        await client.post(f"{SLOTS}/morning/apply", headers=seed["owner_auth"])
        await client.post(f"{SLOTS}/night/apply", headers=seed["owner_auth"])
        avail = await _availability(db, seed["outlet_id"])
        assert avail[shared] is True
        assert avail[only_morning] is False


@pytest.mark.asyncio
class TestApplySkipsOutOfStock:
    async def test_a_tracked_zero_stock_dish_is_never_turned_on(
            self, client, seed, db):
        """is_available=false there means "there are none" — written by the
        stock path (stock.py:171-174). A menu switch must not overrule it."""
        sold_out = await _add_item(db, seed, "Sold Out", available=False, stock=0)
        fine = await _add_item(db, seed, "In Stock", available=False, stock=5)
        await _put(client, seed, "morning", [sold_out, fine])

        r = await client.post(f"{SLOTS}/morning/apply",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["turned_on"] == 1, "only the in-stock dish comes on"
        assert body["skipped_out_of_stock"] == 1

        avail = await _availability(db, seed["outlet_id"])
        assert avail[sold_out] is False, "a sold-out dish must stay off"
        assert avail[fine] is True

    async def test_an_untracked_dish_is_not_treated_as_sold_out(
            self, client, seed, db):
        """stock_remaining IS NULL is UNTRACKED (unlimited) and is every dish
        until a restaurant sets a number. Reading NULL as zero would refuse to
        turn on the entire existing menu."""
        untracked = await _add_item(db, seed, "Unlimited",
                                    available=False, stock=None)
        await _put(client, seed, "morning", [untracked])
        body = (await client.post(f"{SLOTS}/morning/apply",
                                  headers=seed["owner_auth"])).json()
        assert body["turned_on"] == 1
        assert body["skipped_out_of_stock"] == 0
        assert (await _availability(db, seed["outlet_id"]))[untracked] is True

    async def test_skipped_is_reported_on_a_repeat_apply_too(
            self, client, seed, db):
        """It describes the state the owner is handed, not this call's delta."""
        sold_out = await _add_item(db, seed, "Gone", available=False, stock=0)
        ok = await _add_item(db, seed, "Here", available=False, stock=3)
        await _put(client, seed, "morning", [sold_out, ok])
        await client.post(f"{SLOTS}/morning/apply", headers=seed["owner_auth"])
        again = (await client.post(f"{SLOTS}/morning/apply",
                                   headers=seed["owner_auth"])).json()
        assert again["turned_on"] == 0
        assert again["skipped_out_of_stock"] == 1


@pytest.mark.asyncio
class TestEmptySlot:
    async def test_applying_a_never_saved_slot_is_422_and_changes_nothing(
            self, client, seed, db):
        before = await _availability(db, seed["outlet_id"])
        r = await client.post(f"{SLOTS}/afternoon/apply",
                              headers=seed["owner_auth"])
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "SLOT_EMPTY"
        assert await _availability(db, seed["outlet_id"]) == before, \
            "an empty apply must never turn the whole menu off"

    async def test_applying_an_emptied_slot_is_422_and_changes_nothing(
            self, client, seed, db):
        await _put(client, seed, "morning", [seed["menu_item_id"]])
        await _put(client, seed, "morning", [])
        before = await _availability(db, seed["outlet_id"])
        r = await client.post(f"{SLOTS}/morning/apply",
                              headers=seed["owner_auth"])
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "SLOT_EMPTY"
        assert await _availability(db, seed["outlet_id"]) == before


@pytest.mark.asyncio
class TestCrossOutlet:
    async def test_applying_a_slot_cannot_touch_another_outlets_dishes(
            self, client, seed, db):
        other = await _second_outlet(db)
        mine = await _add_item(db, seed, "Mine", available=False)
        await _put(client, seed, "morning", [mine])

        before_other = await _availability(db, other["outlet_id"])
        r = await client.post(f"{SLOTS}/morning/apply",
                              headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert await _availability(db, other["outlet_id"]) == before_other, \
            "outlet B's menu must be untouched by outlet A's switch"
        assert (await _availability(db, seed["outlet_id"]))[mine] is True

    async def test_each_outlets_slots_are_its_own(self, client, seed, db):
        other = await _second_outlet(db)
        await _put(client, seed, "morning", [seed["menu_item_id"]])
        g = await client.get(SLOTS, headers=other["auth"])
        assert g.status_code == 200, g.text
        assert all(s["item_ids"] == [] for s in g.json()), \
            "outlet B must not see outlet A's slot membership"

    async def test_outlet_b_applying_its_own_slot_leaves_a_alone(
            self, client, seed, db):
        other = await _second_outlet(db)
        mine = await _add_item(db, seed, "A Dish", available=True)
        r = await client.put(f"{SLOTS}/night", headers=other["auth"],
                             json={"item_ids": [other["menu_item_id"]]})
        assert r.status_code == 200, r.text
        before_a = await _availability(db, seed["outlet_id"])
        ap = await client.post(f"{SLOTS}/night/apply", headers=other["auth"])
        assert ap.status_code == 200, ap.text
        assert await _availability(db, seed["outlet_id"]) == before_a
        assert mine in before_a


@pytest.mark.asyncio
class TestSoftDeletedDishes:
    async def test_an_inactive_dish_is_not_counted_as_turned_off(
            self, client, seed, db):
        """DELETE /pos/menu-items sets is_active=false AND is_available=false
        together, so a soft-deleted dish is already off and is not part of
        "every other dish" in any sense the owner means."""
        gone = await _add_item(db, seed, "Deleted", available=False, active=False)
        keep = await _add_item(db, seed, "Kept", available=False)
        await _put(client, seed, "morning", [keep])
        body = (await client.post(f"{SLOTS}/morning/apply",
                                  headers=seed["owner_auth"])).json()
        assert body["turned_on"] == 1
        still_off = await db.scalar(text(
            "SELECT is_available FROM menu_items WHERE id = :i"), {"i": gone})
        assert still_off is False


@pytest.mark.asyncio
class TestSchema:
    """The two tables migration 043 creates, asserted on the live database."""

    async def test_both_tables_exist(self, db):
        for t in ("outlet_meal_slots", "meal_slot_items"):
            assert await db.scalar(text(
                "SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{t}"}), \
                f"{t} is missing — apply migration 043"

    async def test_the_slot_key_check_refuses_a_fifth_key(self, db, seed):
        """The database is the backstop behind the route's 422."""
        with pytest.raises(Exception):
            await db.execute(text(
                "INSERT INTO outlet_meal_slots (outlet_id, slot_key) "
                "VALUES (:o, 'brunch')"), {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_one_slot_per_outlet_and_key(self, db, seed):
        await db.execute(text(
            "INSERT INTO outlet_meal_slots (outlet_id, slot_key) "
            "VALUES (:o, 'morning')"), {"o": seed["outlet_id"]})
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(text(
                "INSERT INTO outlet_meal_slots (outlet_id, slot_key) "
                "VALUES (:o, 'morning')"), {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_deleting_a_dish_removes_it_from_every_slot(
            self, client, seed, db):
        """The CASCADE that stops this feature breaking the existing dish
        delete with a foreign-key violation."""
        doomed = await _add_item(db, seed, "Doomed")
        await _put(client, seed, "morning", [doomed])
        assert await db.scalar(text(
            "SELECT count(*) FROM meal_slot_items WHERE menu_item_id = :i"),
            {"i": doomed}) == 1
        await db.execute(text("DELETE FROM menu_items WHERE id = :i"),
                         {"i": doomed})
        await db.commit()
        assert await db.scalar(text(
            "SELECT count(*) FROM meal_slot_items WHERE menu_item_id = :i"),
            {"i": doomed}) == 0
