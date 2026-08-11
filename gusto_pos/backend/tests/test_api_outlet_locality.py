"""§4 phase 1 — outlet locality.

Covers the three server-side halves of the feature:
  * locality is REQUIRED at owner registration and is stored,
  * admin approval refuses a same-city name+locality duplicate,
  * the customer discovery payload carries locality + coordinates so the app
    can render "{Name} · {Locality}" and hand off to Maps.

Everything runs against the local carevo_test database (see conftest).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import API


@pytest.fixture(autouse=True)
def _reset_register_rate_limit():
    """/register is capped at 5/hour per IP by an in-process dict, and every
    test here shares one process and one client IP. Without this the sixth
    registration in the suite fails with 429 for reasons that have nothing to
    do with what is being tested."""
    from app.modules.carevo_customer import service as svc

    svc._register_hits.clear()
    yield
    svc._register_hits.clear()


def _payload(tag: str, **over):
    """A registration body that passes every OTHER validation, so a test that
    changes one field is testing exactly that field."""
    body = {
        "restaurant_name": f"TEST_CAREVO_Diner_{tag}",
        "city": "Bengaluru",
        "locality": "Koramangala",
        "phone_number": "9876500000",
        "email": f"test_carevo_{tag}@example.com",
        "username": f"test_carevo_{tag}",
        "password": "correct-horse-battery",
        "upi_id": "test@upi",
        "latitude": 12.9352,
        "longitude": 77.6245,
    }
    body.update(over)
    return body


async def _register(client, tag: str, **over):
    return await client.post(f"{API}/register", json=_payload(tag, **over))


async def _set_status(db, outlet_id: str, status: str):
    await db.execute(
        text("UPDATE outlets SET verification_status = :s WHERE id = :i"),
        {"s": status, "i": outlet_id},
    )
    await db.commit()


# --------------------------- registration ----------------------------------
class TestRegistrationRequiresLocality:
    async def test_missing_locality_is_rejected(self, client):
        tag = uuid.uuid4().hex[:8]
        body = _payload(tag)
        del body["locality"]
        r = await client.post(f"{API}/register", json=body)
        assert r.status_code == 422, r.text
        assert "locality" in r.text

    async def test_blank_locality_is_rejected(self, client):
        """min_length=2 — a space-bar answer must not satisfy a required field."""
        r = await _register(client, uuid.uuid4().hex[:8], locality=" ")
        assert r.status_code == 422, r.text

    async def test_locality_is_stored_on_the_outlet(self, client, db):
        tag = uuid.uuid4().hex[:8]
        r = await _register(client, tag, locality="Indiranagar")
        assert r.status_code == 201, r.text

        row = (await db.execute(
            text("SELECT locality, city FROM outlets WHERE id = :i"),
            {"i": r.json()["outlet_id"]},
        )).first()
        assert row.locality == "Indiranagar"
        assert row.city == "Bengaluru"

    async def test_locality_is_trimmed(self, client, db):
        """Stored trimmed, because the approval collision check compares on the
        stored value and ' HSR Layout' must collide with 'HSR Layout'."""
        tag = uuid.uuid4().hex[:8]
        r = await _register(client, tag, locality="  HSR Layout  ")
        assert r.status_code == 201, r.text
        stored = (await db.execute(
            text("SELECT locality FROM outlets WHERE id = :i"),
            {"i": r.json()["outlet_id"]},
        )).scalar()
        assert stored == "HSR Layout"


# ------------------------ approval collision guard --------------------------
class TestApprovalCollisionGuard:
    async def test_duplicate_name_and_locality_blocks_approval(
        self, client, db, seed
    ):
        """Two outlets, same name, same locality, same city. The first approves;
        the second is refused so customers never see two identical entries."""
        name = f"TEST_CAREVO_Twin_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Jayanagar")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Jayanagar")
        assert a.status_code == 201 and b.status_code == 201

        first = await client.post(
            f"{API}/admin/outlets/{a.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert first.status_code == 200, first.text

        second = await client.post(
            f"{API}/admin/outlets/{b.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert second.status_code == 409, second.text
        assert "already exists" in second.json()["detail"]

        # The refusal must not have half-applied: the blocked outlet is still
        # pending, so a later approval is still possible once resolved.
        still = (await db.execute(
            text("SELECT verification_status FROM outlets WHERE id = :i"),
            {"i": b.json()["outlet_id"]},
        )).scalar()
        assert still == "pending_verification"

    async def test_same_name_different_locality_is_allowed(self, client, seed):
        """The whole point of locality: two real branches of one chain."""
        name = f"TEST_CAREVO_Chain_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Whitefield")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Marathahalli")

        for reg in (a, b):
            r = await client.post(
                f"{API}/admin/outlets/{reg.json()['outlet_id']}/approve",
                headers=seed["admin_auth"])
            assert r.status_code == 200, r.text

    async def test_same_name_and_locality_different_city_is_allowed(
        self, client, seed
    ):
        """'MG Road' exists in many cities; the rule is scoped per city."""
        name = f"TEST_CAREVO_City_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8], restaurant_name=name,
                            city="Bengaluru", locality="MG Road")
        b = await _register(client, uuid.uuid4().hex[:8], restaurant_name=name,
                            city="Chennai", locality="MG Road")

        for reg in (a, b):
            r = await client.post(
                f"{API}/admin/outlets/{reg.json()['outlet_id']}/approve",
                headers=seed["admin_auth"])
            assert r.status_code == 200, r.text

    async def test_collision_is_case_and_whitespace_insensitive(
        self, client, seed
    ):
        """A guard that 'koramangala ' slips past is a guard in name only."""
        name = f"TEST_CAREVO_Case_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Koramangala")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name.upper(),
                            locality="  koramangala  ")

        ok = await client.post(
            f"{API}/admin/outlets/{a.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert ok.status_code == 200, ok.text

        clash = await client.post(
            f"{API}/admin/outlets/{b.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert clash.status_code == 409, clash.text

    async def test_pending_duplicate_does_not_block(self, client, seed):
        """Only ACTIVE outlets are conflicts. Two duplicates may sit in the
        queue together — approving the FIRST is what makes the second a clash,
        so the first approval must not be blocked by the second's existence."""
        name = f"TEST_CAREVO_Queue_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="BTM Layout")
        await _register(client, uuid.uuid4().hex[:8],
                        restaurant_name=name, locality="BTM Layout")

        r = await client.post(
            f"{API}/admin/outlets/{a.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text

    async def test_rejected_duplicate_does_not_block(self, client, db, seed):
        """A rejected outlet is not live, so it must not hold a name hostage."""
        name = f"TEST_CAREVO_Rej_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Hebbal")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Hebbal")

        await _set_status(db, a.json()["outlet_id"], "rejected")
        r = await client.post(
            f"{API}/admin/outlets/{b.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text

    async def test_deactivated_duplicate_does_not_block(self, client, db, seed):
        """Same reasoning as rejected: soft-deleted outlets are not visible to
        customers, so they cannot produce a duplicate listing."""
        name = f"TEST_CAREVO_Deact_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Yelahanka")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Yelahanka")

        aid = a.json()["outlet_id"]
        await _set_status(db, aid, "active")
        await db.execute(
            text("UPDATE outlets SET deactivated_at = now() WHERE id = :i"),
            {"i": aid})
        await db.commit()

        r = await client.post(
            f"{API}/admin/outlets/{b.json()['outlet_id']}/approve",
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text

    async def test_rejection_is_never_blocked_by_a_collision(
        self, client, seed
    ):
        """The guard gates APPROVAL only. An admin must always be able to
        reject, and a duplicate is a likely reason to want to."""
        name = f"TEST_CAREVO_RejPath_{uuid.uuid4().hex[:8]}"
        a = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Basavanagudi")
        b = await _register(client, uuid.uuid4().hex[:8],
                            restaurant_name=name, locality="Basavanagudi")

        await client.post(f"{API}/admin/outlets/{a.json()['outlet_id']}/approve",
                          headers=seed["admin_auth"])
        r = await client.post(
            f"{API}/admin/outlets/{b.json()['outlet_id']}/reject",
            headers=seed["admin_auth"])
        assert r.status_code == 200, r.text


# ---------------------- customer discovery payload --------------------------
class TestCustomerOutletPayload:
    async def test_locality_and_coordinates_are_returned(
        self, client, db, seed
    ):
        """The Maps button and the "{Name} · {Locality}" line both depend on
        these fields reaching the app; /customer/outlets returned neither
        before this change."""
        await db.execute(text("""
            UPDATE outlets SET locality = 'Koramangala', city = 'Bengaluru',
                               latitude = 12.9352, longitude = 77.6245
            WHERE id = :i"""), {"i": seed["outlet_id"]})
        await db.commit()

        r = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        row = next(o for o in r.json() if o["id"] == seed["outlet_id"])

        assert row["locality"] == "Koramangala"
        # Numbers, not strings: the column is `numeric` (-> Decimal), which
        # would serialise as a quoted string and break the Maps URL.
        assert isinstance(row["latitude"], float)
        assert isinstance(row["longitude"], float)
        assert row["latitude"] == pytest.approx(12.9352)
        assert row["longitude"] == pytest.approx(77.6245)

    async def test_address_joins_locality_and_city(self, client, db, seed):
        await db.execute(text("""
            UPDATE outlets SET locality = 'Indiranagar', city = 'Bengaluru'
            WHERE id = :i"""), {"i": seed["outlet_id"]})
        await db.commit()

        r = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        row = next(o for o in r.json() if o["id"] == seed["outlet_id"])
        assert row["address"] == "Indiranagar, Bengaluru"

    async def test_outlet_without_locality_still_renders(
        self, client, db, seed
    ):
        """Outlets predating migration 012 have no locality. The address must
        fall back to the city alone rather than emitting ', Bengaluru'."""
        await db.execute(text("""
            UPDATE outlets SET locality = NULL, city = 'Bengaluru',
                               latitude = NULL, longitude = NULL
            WHERE id = :i"""), {"i": seed["outlet_id"]})
        await db.commit()

        r = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        row = next(o for o in r.json() if o["id"] == seed["outlet_id"])
        assert row["locality"] is None
        assert row["address"] == "Bengaluru"
        # No pin -> the app hides the Maps button rather than linking nowhere.
        assert row["latitude"] is None
        assert row["longitude"] is None

    async def test_gps_distance_sort_is_unchanged(self, client, db, seed):
        """Locality must not have displaced GPS distance-sorting — distance is
        still computed from coordinates, not inferred from the area name."""
        await db.execute(text("""
            UPDATE outlets SET locality = 'Koramangala',
                               latitude = 12.9352, longitude = 77.6245
            WHERE id = :i"""), {"i": seed["outlet_id"]})
        await db.commit()

        r = await client.get(
            f"{API}/customer/outlets?lat=12.9352&lng=77.6245",
            headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        row = next(o for o in r.json() if o["id"] == seed["outlet_id"])
        assert row["distance_km"] == pytest.approx(0.0, abs=0.01)


# ------------------------------ admin list ----------------------------------
class TestAdminOutletList:
    async def test_admin_list_exposes_locality(self, client, db, seed):
        """Admins need to see it to act on a 409 from the collision guard."""
        await db.execute(
            text("UPDATE outlets SET locality = 'Jayanagar' WHERE id = :i"),
            {"i": seed["outlet_id"]})
        await db.commit()

        r = await client.get(f"{API}/admin/outlets", headers=seed["admin_auth"])
        assert r.status_code == 200, r.text
        row = next(o for o in r.json() if o["id"] == seed["outlet_id"])
        assert row["locality"] == "Jayanagar"

    async def test_admin_list_still_leaks_no_password_material(
        self, client, seed
    ):
        """Guard on the §3 owner-username column, re-asserted here because this
        change edits the same SELECT."""
        r = await client.get(f"{API}/admin/outlets", headers=seed["admin_auth"])
        blob = r.text.lower()
        for leak in ("hashed_password", "password", "$2b$", "hashed"):
            assert leak not in blob, f"admin outlet list exposed '{leak}'"
