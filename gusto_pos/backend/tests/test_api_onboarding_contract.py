"""The /register contract that BOTH onboarding UIs must satisfy.

One endpoint backs two forms — owner_app's self-signup and admin_app's
admin-assisted onboarding — so the required-field set is a shared contract.
Both forms were found sending an incomplete body: neither sent `locality`, and
admin_app additionally omitted `phone_number` and `email`. Every submission was
rejected 422 before it ever reached the pending queue.

These tests pin the contract so a field added to RegisterIn cannot silently
break a form again: the "every required field" test enumerates them from the
schema itself rather than from a hand-written list.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import API

from app.modules.carevo_customer.schema import RegisterIn


@pytest.fixture(autouse=True)
def _reset_register_rate_limit():
    """/register is capped at 5/hour per IP by an in-process dict, and these
    tests share one process and one client IP."""
    from app.modules.carevo_customer import service as svc

    svc._register_hits.clear()
    yield
    svc._register_hits.clear()


def _complete_payload(tag: str, **over):
    """Exactly what a correctly-built onboarding form now sends."""
    body = {
        "restaurant_name": f"TEST_CAREVO_Onboard_{tag}",
        "city": "Bengaluru",
        "locality": "Koramangala",
        "phone_number": "9876500000",
        "email": f"test_carevo_ob_{tag}@example.com",
        "username": f"test_carevo_ob_{tag}",
        "password": "correct-horse-battery",
        "upi_id": "test@upi",
        "latitude": 12.9352,
        "longitude": 77.6245,
    }
    body.update(over)
    return body


def _required_field_names() -> set[str]:
    """Read the required set off the Pydantic model, so this test tracks the
    schema instead of a list that drifts from it."""
    return {
        name for name, f in RegisterIn.model_fields.items() if f.is_required()
    }


class TestRequiredFieldContract:
    async def test_missing_locality_is_a_clear_422_not_a_500(self, client):
        """The exact failure both forms were producing. It must be a readable
        validation error naming the field — not a generic server error."""
        tag = uuid.uuid4().hex[:8]
        body = _complete_payload(tag)
        del body["locality"]

        r = await client.post(f"{API}/register", json=body)

        assert r.status_code == 422, r.text
        assert r.status_code != 500, "a missing field must never surface as a 500"
        assert "locality" in r.text, "the response must name the offending field"

    async def test_every_required_field_is_rejected_when_absent(self, client):
        """Enumerated from the schema, so a newly-required field is covered the
        moment it is added — which is exactly the change that broke the forms."""
        for field in sorted(_required_field_names()):
            tag = uuid.uuid4().hex[:8]
            body = _complete_payload(tag)
            body.pop(field, None)

            r = await client.post(f"{API}/register", json=body)

            assert r.status_code == 422, (
                f"omitting '{field}' should be a 422, got {r.status_code}: {r.text}"
            )

    async def test_locality_is_currently_among_the_required_fields(self):
        """Guards the premise of this whole file. If locality ever stops being
        required, the UI work here should be revisited rather than left."""
        assert "locality" in _required_field_names()
        assert "phone_number" in _required_field_names()
        assert "email" in _required_field_names()

    async def test_complete_payload_succeeds(self, client, db):
        """The positive case: everything present -> a real pending outlet."""
        tag = uuid.uuid4().hex[:8]
        r = await client.post(f"{API}/register", json=_complete_payload(tag))

        assert r.status_code == 201, r.text
        out = r.json()
        assert out["verification_status"] == "pending_verification"

        row = (await db.execute(text(
            "SELECT locality, city, phone_number, latitude, longitude, "
            "       verification_status, is_visible "
            "FROM outlets WHERE id = :i"), {"i": out["outlet_id"]})).first()
        assert row.locality == "Koramangala"
        assert row.city == "Bengaluru"
        assert row.phone_number == "9876500000"
        assert float(row.latitude) == pytest.approx(12.9352)
        assert float(row.longitude) == pytest.approx(77.6245)
        # Never live until an admin approves it, whichever form created it.
        assert row.verification_status == "pending_verification"
        assert row.is_visible is False


class TestAdminAssistedMatchesSelfSignup:
    """admin_app's onboarding posts the SAME body to the SAME endpoint as
    owner_app. These assert the two produce an identical outcome, so the admin
    path cannot drift into a second, subtly different onboarding."""

    async def test_admin_shaped_body_creates_pending_outlet_and_owner_login(
        self, client, db
    ):
        tag = uuid.uuid4().hex[:8]
        # Field-for-field what the admin form now sends.
        body = _complete_payload(tag, restaurant_name=f"TEST_CAREVO_Admin_{tag}")
        r = await client.post(f"{API}/register", json=body)
        assert r.status_code == 201, r.text
        out = r.json()

        # Same outlet shape...
        outlet = (await db.execute(text(
            "SELECT verification_status, is_visible, locality FROM outlets WHERE id = :i"),
            {"i": out["outlet_id"]})).first()
        assert outlet.verification_status == "pending_verification"
        assert outlet.is_visible is False
        assert outlet.locality == "Koramangala"

        # ...and a usable owner login attached to it.
        user = (await db.execute(text(
            "SELECT username, email, is_active, hashed_password FROM users "
            "WHERE outlet_id = :i"), {"i": out["outlet_id"]})).first()
        assert user.username == body["username"]
        assert user.email == body["email"].lower()
        assert user.is_active is True
        assert user.hashed_password and user.hashed_password != body["password"], \
            "password must be stored hashed, never in the clear"

    async def test_owner_can_log_in_after_admin_assisted_onboarding(self, client):
        """The point of the admin flow: hand the owner working credentials."""
        tag = uuid.uuid4().hex[:8]
        body = _complete_payload(tag)
        assert (await client.post(f"{API}/register", json=body)).status_code == 201

        login = await client.post(
            f"{API}/auth/login",
            data={"username": body["username"], "password": body["password"]},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login.status_code == 200, login.text
        assert login.json().get("access_token")

    async def test_unknown_city_is_refused_with_a_usable_message(self, client):
        """The admin form uses a dropdown of approved cities precisely because
        a free-typed city is refused here."""
        tag = uuid.uuid4().hex[:8]
        r = await client.post(
            f"{API}/register",
            json=_complete_payload(tag, city="Atlantis"),
        )
        assert r.status_code == 422, r.text
        assert "city" in r.text.lower()

    async def test_coordinates_remain_optional_server_side(self, client, db):
        """Both forms now require lat/lng, but the SERVER does not — recorded
        here so nobody assumes an outlet can never exist without a pin. Outlets
        created before this change have NULL coordinates."""
        tag = uuid.uuid4().hex[:8]
        body = _complete_payload(tag)
        del body["latitude"]
        del body["longitude"]

        r = await client.post(f"{API}/register", json=body)

        assert r.status_code == 201, r.text
        row = (await db.execute(text(
            "SELECT latitude, longitude FROM outlets WHERE id = :i"),
            {"i": r.json()["outlet_id"]})).first()
        assert row.latitude is None and row.longitude is None
