"""PATCH /pos/outlet/location — the owner pins their own restaurant.

The pin feeds the customer app's distance sort, so two things matter beyond
"does it store a number": it must be scoped to the caller's own outlet (a pin
moved onto someone else's street hijacks that sort), and a setter must return
the FULL outlet — the shared _load_owner_outlet shape — or the app blanks the
hours it just saved when the owner merely moves the pin.
"""
import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio

# Bengaluru, near enough. Chosen with more than 2 decimals so a rounding or
# column-precision problem shows up rather than surviving the assertion.
LAT, LNG = 12.97194, 77.59369


class TestPinning:
    async def test_the_pin_is_stored(self, client, seed, db):
        r = await client.patch(f"{API}/pos/outlet/location",
                               headers=seed["owner_auth"],
                               json={"latitude": LAT, "longitude": LNG})
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] == pytest.approx(LAT)
        assert r.json()["longitude"] == pytest.approx(LNG)

        row = (await db.execute(text(
            "SELECT latitude, longitude FROM outlets WHERE id = :o"
        ), {"o": seed["outlet_id"]})).first()
        assert float(row.latitude) == pytest.approx(LAT)
        assert float(row.longitude) == pytest.approx(LNG)

    async def test_an_unpinned_outlet_reads_back_null(self, client, seed):
        """Null, never (0, 0) — the distance sort must be able to skip an
        outlet that has no pin rather than place it in the Gulf of Guinea."""
        r = await client.get(f"{API}/pos/outlet", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["latitude"] is None
        assert r.json()["longitude"] is None

    async def test_the_pin_can_be_moved(self, client, seed):
        await client.patch(f"{API}/pos/outlet/location", headers=seed["owner_auth"],
                           json={"latitude": LAT, "longitude": LNG})
        r = await client.patch(f"{API}/pos/outlet/location",
                               headers=seed["owner_auth"],
                               json={"latitude": 19.076, "longitude": 72.8777})
        assert r.json()["latitude"] == pytest.approx(19.076)

    async def test_it_returns_the_full_outlet_and_keeps_the_hours(
        self, client, seed
    ):
        """The regression the shared loader exists to prevent: a setter that
        returned only what it changed would make the app null the schedule."""
        await client.patch(f"{API}/pos/outlet/hours", headers=seed["owner_auth"],
                           json={"opening_time": "09:00", "closing_time": "22:00"})

        r = await client.patch(f"{API}/pos/outlet/location",
                               headers=seed["owner_auth"],
                               json={"latitude": LAT, "longitude": LNG})
        body = r.json()
        assert body["opening_time"] == "09:00"
        assert body["closing_time"] == "22:00"
        assert body["location_name"], "the whole OwnerOutletOut shape comes back"
        assert "order_status" in body

    async def test_the_hours_endpoint_does_not_clear_the_pin(self, client, seed):
        """And the converse — the two controls are independent."""
        await client.patch(f"{API}/pos/outlet/location", headers=seed["owner_auth"],
                           json={"latitude": LAT, "longitude": LNG})
        r = await client.patch(f"{API}/pos/outlet/hours",
                               headers=seed["owner_auth"],
                               json={"opening_time": "08:00", "closing_time": "20:00"})
        assert r.json()["latitude"] == pytest.approx(LAT)


class TestItIsScopedAndValidated:
    async def test_it_needs_a_staff_token(self, client):
        r = await client.patch(f"{API}/pos/outlet/location",
                               json={"latitude": LAT, "longitude": LNG})
        assert r.status_code in (401, 403)

    async def test_it_pins_only_the_callers_own_outlet(self, client, seed, db):
        """There is no outlet_id parameter at all — the outlet comes from the
        caller's account, so there is nothing to tamper with. This asserts the
        consequence: a second outlet is untouched by the first owner's pin."""
        other = (await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city,
                                 is_visible, upi_id, geofence_radius_meters,
                                 verification_status, created_at)
            SELECT gen_random_uuid(), organization_id, 'Other Outlet', 'Testville',
                   true, 'other@upi', 150, 'active', now()
            FROM outlets WHERE id = :o RETURNING id
        """), {"o": seed["outlet_id"]})).scalar()
        await db.commit()

        await client.patch(f"{API}/pos/outlet/location", headers=seed["owner_auth"],
                           json={"latitude": LAT, "longitude": LNG})

        row = (await db.execute(text(
            "SELECT latitude, longitude FROM outlets WHERE id = :o"
        ), {"o": str(other)})).first()
        assert row.latitude is None and row.longitude is None

    @pytest.mark.parametrize("lat,lng", [
        (91, 0),        # past the north pole
        (-91, 0),
        (0, 181),       # past the date line
        (0, -181),
    ])
    async def test_out_of_range_is_refused(self, client, seed, lat, lng):
        """A swapped lat/lng pair is undetectable and gets stored; a value
        outside the range is a guaranteed-wrong pin and is worth refusing.
        The DECIMAL(10,8) column could not hold a latitude of 91 anyway."""
        r = await client.patch(f"{API}/pos/outlet/location",
                               headers=seed["owner_auth"],
                               json={"latitude": lat, "longitude": lng})
        assert r.status_code == 422

    @pytest.mark.parametrize("payload", [
        {"latitude": LAT},               # half a pair is not a location
        {"longitude": LNG},
        {},
    ])
    async def test_both_coordinates_are_required(self, client, seed, payload):
        r = await client.patch(f"{API}/pos/outlet/location",
                               headers=seed["owner_auth"], json=payload)
        assert r.status_code == 422
