"""Owner self-serve payment settings (migration 035).

GET and PATCH /api/v1/pos/outlet/payment-methods — the screen where a
restaurant decides how it takes money, without going through CareVo.

THE THREE ASSERTIONS THAT MATTER MOST
-------------------------------------
1. `TestRoleGate.test_a_role_less_owner_account_is_allowed` — in this schema an
   outlet's owner account has NO role row (register_owner never writes one), so
   a strict OWNER-or-MANAGER allow-list would lock every real owner out of their
   own settings. This pins the deviation that makes the feature usable.

2. `TestVpaChangeVoidsAttestation` — the old attestation was about the old
   string. If a one-character typo inherited it, direct UPI would stay ON
   against a VPA nobody has proven they control, and customers' money would go
   to a stranger with CareVo not in the path to recover it.

3. `TestCashfreeLock` — the owner's flag is a preference, cashfree_unlocked is
   permission, and permission is not the owner's to grant.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash
from app.modules.carevo_customer.service import (
    PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL, CarevoService,
)
from tests.conftest import API

SETTINGS = f"{API}/pos/outlet/payment-methods"

GOOD_VPA = "testrestaurant@okaxis"
OTHER_VPA = "testrestaurant2@okhdfcbank"


# ------------------------------- helpers -------------------------------------

async def _grant_role(db, user_id, role_name: str) -> None:
    """Attach a seeded role to a staff user, creating the role if absent."""
    rid = await db.scalar(text("SELECT id FROM roles WHERE name = :n"),
                          {"n": role_name})
    if rid is None:
        rid = await db.scalar(text(
            "INSERT INTO roles (name, permissions, created_at) "
            "VALUES (:n, '{}'::jsonb, now()) RETURNING id"), {"n": role_name})
    await db.execute(text(
        "INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) "
        "ON CONFLICT DO NOTHING"), {"u": str(user_id), "r": rid})
    await db.commit()


async def _staff_with_role(db, seed, role_name: str | None):
    """A fresh staff account at the seeded outlet, optionally with one role."""
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    username = f"{(role_name or 'norole').lower()}_{tag}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, :h, true, :o, now())"""),
        {"i": str(uid), "u": username,
         "h": get_password_hash("correct-horse"), "o": seed["outlet_id"]})
    await db.commit()
    if role_name:
        await _grant_role(db, uid, role_name)
    return {"id": str(uid),
            "auth": {"Authorization":
                     f"Bearer {create_access_token(subject=username)}"}}


async def _outlet_row(db, outlet_id):
    return (await db.execute(text("""
        SELECT payment_prepaid_enabled, payment_pay_at_pickup_enabled,
               payment_upi_manual_enabled, cashfree_unlocked, upi_vpa,
               upi_payee_name, upi_attested_at, payment_settings_updated_at,
               payment_settings_updated_by
          FROM outlets WHERE id = :i
    """), {"i": str(outlet_id)})).first()


def _body(**kw):
    base = {"prepaid": True, "pay_at_pickup": False, "upi_manual": False}
    base.update(kw)
    return base


# ============================== 1. the role gate =============================

class TestRoleGate:
    """The role model: `roles` (SERIAL id, unique name) + the `user_roles` m2m,
    name-matched case-insensitively — the same shape is_super_admin and
    _PIN_ADMIN_ROLES already use."""

    async def test_a_role_less_owner_account_is_allowed(self, client, db, seed):
        """THE DEVIATION, pinned.

        CarevoService.register_owner inserts the owner's users row without any
        user_roles row, and no migration backfills one — so every real outlet
        owner is role-less. A strict allow-list would 403 all of them.
        """
        roles = await db.scalar(text(
            "SELECT count(*) FROM user_roles WHERE user_id = :u"),
            {"u": seed["owner_id"]})
        assert roles == 0, "the fixture reproduces a real owner: no roles"

        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("role", ["Owner", "Manager", "Admin"])
    async def test_privileged_roles_are_allowed(self, client, db, seed, role):
        who = await _staff_with_role(db, seed, role)
        r = await client.get(SETTINGS, headers=who["auth"])
        assert r.status_code == 200, r.text

    @pytest.mark.parametrize("role", ["Waiter", "Kitchen"])
    async def test_waiters_and_kitchen_are_refused(self, client, db, seed, role):
        """The requirement this gate exists for."""
        who = await _staff_with_role(db, seed, role)

        r = await client.get(SETTINGS, headers=who["auth"])
        assert r.status_code == 403, r.text

        w = await client.patch(SETTINGS, headers=who["auth"], json=_body())
        assert w.status_code == 403, w.text

    async def test_a_waiter_who_is_also_owner_is_allowed(self, client, db, seed):
        """A privileged role wins over a staff role — somebody who waits tables
        and runs the place is still the person who runs the place."""
        who = await _staff_with_role(db, seed, "Waiter")
        await _grant_role(db, who["id"], "Owner")
        r = await client.get(SETTINGS, headers=who["auth"])
        assert r.status_code == 200, r.text

    async def test_a_super_admin_is_allowed(self, client, db, seed):
        """Admins act across outlets, so they pass this gate too — but they
        still need an outlet, which _require_outlet enforces separately."""
        who = await _staff_with_role(db, seed, "SUPER_ADMIN")
        r = await client.get(SETTINGS, headers=who["auth"])
        assert r.status_code == 200, r.text

    async def test_unauthenticated_is_refused(self, client):
        r = await client.get(SETTINGS)
        assert r.status_code in (401, 403)

    async def test_staff_without_an_outlet_is_refused(self, client, db, seed):
        """_require_outlet still applies on top of the role check."""
        tag = uuid.uuid4().hex[:8]
        await db.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active,
                               created_at)
            VALUES (gen_random_uuid(), :u, :h, true, now())"""),
            {"u": f"noout_{tag}", "h": get_password_hash("correct-horse")})
        await db.commit()
        auth = {"Authorization":
                f"Bearer {create_access_token(subject=f'noout_{tag}')}"}
        r = await client.get(SETTINGS, headers=auth)
        assert r.status_code == 403, r.text


# ============================== 2. reading ===================================

class TestGetSettings:
    async def test_defaults_describe_an_existing_outlet(self, client, seed):
        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["prepaid"] is True
        assert body["pay_at_pickup"] is False
        assert body["upi_manual"] is False
        assert body["cashfree_unlocked"] is True, "unchanged for every outlet"
        assert body["upi_vpa"] is None
        assert body["upi_attested"] is False
        assert body["effective_methods"] == [PAY_PREPAID]

    async def test_it_is_scoped_to_the_callers_own_outlet(
            self, client, db, seed):
        """There is no outlet_id parameter, so another outlet cannot be read."""
        other_org = await db.scalar(text(
            "SELECT organization_id FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        oid = uuid.uuid4()
        tag = uuid.uuid4().hex[:8]
        await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city,
                                 is_visible, upi_id, geofence_radius_meters,
                                 verification_status, created_at,
                                 payment_prepaid_enabled,
                                 payment_pay_at_pickup_enabled)
            VALUES (:i,:o,:n,'T', true, 'x@upi', 150, 'active', now(),
                    false, true)"""),
            {"i": str(oid), "o": str(other_org), "n": f"Other {tag}"})
        await db.commit()

        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.json()["outlet_id"] == seed["outlet_id"]


# ========================= 3. the three validation rules =====================

class TestAtLeastOneMethod:
    async def test_all_three_off_is_a_422(self, client, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=False, pay_at_pickup=False,
                                          upi_manual=False))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "NO_PAYMENT_METHOD"

    async def test_the_database_refuses_it_too(self, db, seed):
        """The UI and the service are never the only enforcement point."""
        with pytest.raises(Exception):
            await db.execute(text("""
                UPDATE outlets SET payment_prepaid_enabled = false,
                                   payment_pay_at_pickup_enabled = false,
                                   payment_upi_manual_enabled = false
                 WHERE id = :o"""), {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_pay_at_pickup_alone_is_fine(self, client, db, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=False, pay_at_pickup=True))
        assert r.status_code == 200, r.text
        assert r.json()["pay_at_pickup"] is True
        assert r.json()["prepaid"] is False


class TestCashfreeLock:
    async def test_prepaid_cannot_be_turned_on_while_locked(
            self, client, db, seed):
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false, "
            "       payment_prepaid_enabled = false, "
            "       payment_pay_at_pickup_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=True, pay_at_pickup=True))
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "CASHFREE_LOCKED"
        assert detail["message"] == (
            "Cashfree is currently unavailable for your restaurant.")

        row = await _outlet_row(db, seed["outlet_id"])
        assert row[0] is False, "nothing was written"

    async def test_the_locked_state_is_reported_for_the_toggle(
            self, client, db, seed):
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false, "
            "       payment_pay_at_pickup_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.json()["cashfree_unlocked"] is False

    async def test_prepaid_withdrawn_from_customers_while_locked(
            self, db, seed):
        """The lock reaches the resolver, not just the settings screen."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false, "
            "       payment_pay_at_pickup_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert PAY_PREPAID not in methods
        assert methods == [PAY_AT_PICKUP]

    async def test_an_owner_can_turn_prepaid_off_while_locked(
            self, client, db, seed):
        """The lock blocks turning it ON, never turning it off — otherwise an
        outlet could be trapped with a method it cannot use."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=False, pay_at_pickup=True))
        assert r.status_code == 200, r.text


class TestUpiValidation:
    async def test_upi_needs_a_vpa_and_a_payee(self, client, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "UPI_DETAILS_REQUIRED"

    async def test_upi_needs_the_attestation(self, client, db, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                          upi_payee_name="Test Kitchen",
                                          upi_attested=False))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "UPI_ATTESTATION_REQUIRED"
        assert (await _outlet_row(db, seed["outlet_id"]))[2] is False

    @pytest.mark.parametrize("bad", [
        "nobody", "no-at-sign.example", "@okaxis", "a@", "spaces in@okaxis",
        "x@1234",
        # 260 characters before the @ — over the pattern's 255 but under
        # OwnerPaymentMethodsIn's max_length of 320, so it reaches the shape
        # check rather than being turned away by Pydantic first. That ordering
        # is the point: this asserts OUR message, not the framework's.
        "a" * 260 + "@okaxis",
    ])
    async def test_a_malformed_vpa_is_a_422(self, client, seed, bad):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_vpa=bad,
                                          upi_payee_name="Test Kitchen"))
        assert r.status_code == 422, f"{bad!r}: {r.text}"
        assert r.json()["detail"]["error"] == "INVALID_UPI_ID"

    async def test_the_database_refuses_a_malformed_vpa_too(self, db, seed):
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE outlets SET upi_vpa = 'nope' WHERE id = :o"),
                {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_the_database_refuses_upi_on_without_details(self, db, seed):
        """ck_outlets_upi_manual_requires_vpa — the invariant that makes an
        order against an unattested VPA impossible."""
        with pytest.raises(Exception):
            await db.execute(text(
                "UPDATE outlets SET payment_upi_manual_enabled = true "
                " WHERE id = :o"), {"o": seed["outlet_id"]})
            await db.commit()
        await db.rollback()

    async def test_the_happy_path_stamps_the_attestation(
            self, client, db, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                          upi_payee_name="Test Kitchen",
                                          upi_attested=True))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["upi_manual"] is True
        assert body["upi_vpa"] == GOOD_VPA
        assert body["upi_payee_name"] == "Test Kitchen"
        assert body["upi_attested"] is True
        assert PAY_UPI_MANUAL in body["effective_methods"]

        row = await _outlet_row(db, seed["outlet_id"])
        assert row[6] is not None, "upi_attested_at stamped"
        assert row[7] is not None, "payment_settings_updated_at stamped"
        assert str(row[8]) == seed["owner_id"], "and by whom"


class TestVpaChangeVoidsAttestation:
    """The rule most worth being strict about: the old proof was about the old
    string, and a typo inheriting it sends customers' money to a stranger."""

    @pytest.fixture
    async def attested(self, client, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                          upi_payee_name="Test Kitchen",
                                          upi_attested=True))
        assert r.status_code == 200, r.text
        return r.json()

    async def test_changing_the_vpa_without_re_attesting_is_refused(
            self, client, db, seed, attested):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=OTHER_VPA,
                                          upi_payee_name="Test Kitchen",
                                          upi_attested=False))
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["error"] == "UPI_ATTESTATION_REQUIRED"
        # Refused outright, so the old VPA and its proof both survive.
        row = await _outlet_row(db, seed["outlet_id"])
        assert row[4] == GOOD_VPA
        assert row[6] is not None

    async def test_changing_the_vpa_with_upi_off_clears_the_attestation(
            self, client, db, seed, attested):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=True, upi_manual=False,
                                          upi_vpa=OTHER_VPA,
                                          upi_payee_name="Test Kitchen"))
        assert r.status_code == 200, r.text
        assert r.json()["upi_attested"] is False, "the old proof is void"
        assert r.json()["upi_vpa"] == OTHER_VPA
        assert r.json()["upi_manual"] is False
        assert PAY_UPI_MANUAL not in r.json()["effective_methods"]

    async def test_re_attesting_the_new_vpa_turns_it_back_on(
            self, client, db, seed, attested):
        first = await _outlet_row(db, seed["outlet_id"])
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=OTHER_VPA,
                                          upi_payee_name="Test Kitchen",
                                          upi_attested=True))
        assert r.status_code == 200, r.text
        assert r.json()["upi_manual"] is True
        assert r.json()["upi_vpa"] == OTHER_VPA
        row = await _outlet_row(db, seed["outlet_id"])
        assert row[6] is not None and row[6] >= first[6], "re-stamped"

    async def test_an_unchanged_vpa_keeps_its_attestation(
            self, client, db, seed, attested):
        """Editing the payee name must not force a re-attestation — the proof
        is about the VPA, which did not change."""
        before = (await _outlet_row(db, seed["outlet_id"]))[6]
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                          upi_payee_name="Renamed Kitchen",
                                          upi_attested=False))
        assert r.status_code == 200, r.text
        assert r.json()["upi_manual"] is True
        assert r.json()["upi_payee_name"] == "Renamed Kitchen"
        assert (await _outlet_row(db, seed["outlet_id"]))[6] == before


# ============================ 4. the admin route =============================

class TestAdminRouteStillWorks:
    async def test_it_can_set_the_platform_lock(self, client, db, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": True,
                  "cashfree_unlocked": False})
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_unlocked"] is False
        # The owner's own flag is untouched; only permission changed.
        assert r.json()["payment_prepaid_enabled"] is True
        # And prepaid is withdrawn from customers despite the flag being on.
        assert PAY_PREPAID not in r.json()["effective_methods"]

    async def test_omitting_the_new_fields_leaves_them_unchanged(
            self, client, db, seed):
        """An existing admin caller that predates 035 keeps working."""
        await client.patch(SETTINGS, headers=seed["owner_auth"],
                          json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                     upi_payee_name="Test Kitchen",
                                     upi_attested=True))
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False})
        assert r.status_code == 200, r.text
        assert r.json()["payment_upi_manual_enabled"] is True, "left alone"
        assert r.json()["cashfree_unlocked"] is True, "left alone"

    async def test_upi_alone_satisfies_the_admin_floor(self, client, db, seed):
        await client.patch(SETTINGS, headers=seed["owner_auth"],
                          json=_body(upi_manual=True, upi_vpa=GOOD_VPA,
                                     upi_payee_name="Test Kitchen",
                                     upi_attested=True))
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": False,
                  "upi_manual": True})
        assert r.status_code == 200, r.text

    async def test_all_three_off_is_still_refused(self, client, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": False,
                  "upi_manual": False})
        assert r.status_code == 422, r.text

    async def test_an_owner_cannot_reach_the_admin_route(self, client, seed):
        r = await client.patch(
            f"{API}/admin/outlets/{seed['outlet_id']}/payment-methods",
            headers=seed["owner_auth"],
            json={"prepaid": True, "pay_at_pickup": True,
                  "cashfree_unlocked": True})
        assert r.status_code in (401, 403)

    async def test_the_owner_route_cannot_set_the_lock(self, client, db, seed):
        """cashfree_unlocked is not in OwnerPaymentMethodsIn at all, so even a
        caller that sends it cannot change it — extra keys are ignored."""
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false, "
            "       payment_pay_at_pickup_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json={"prepaid": False, "pay_at_pickup": True,
                                     "upi_manual": False,
                                     "cashfree_unlocked": True})
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_unlocked"] is False, "still locked"


# ============ 5. Cashfree invisible until activated (migration 036) =========

class TestNewOutletIsCashfreeLocked:
    """036 flipped the DEFAULT so a restaurant joining now has online payment
    invisible until CareVo activates it — without touching existing outlets."""

    @pytest.fixture
    async def fresh_outlet(self, db, seed):
        """An outlet created the way every real path creates one: WITHOUT
        naming cashfree_unlocked. That omission is what the test is about."""
        org = await db.scalar(text(
            "SELECT organization_id FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        oid = uuid.uuid4()
        tag = uuid.uuid4().hex[:8]
        await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city,
                                 is_visible, upi_id, geofence_radius_meters,
                                 verification_status, created_at)
            VALUES (:i,:o,:n,'Testville', true, 'new@upi', 150, 'active',
                    now())"""),
            {"i": str(oid), "o": str(org), "n": f"Brand New {tag}"})
        await db.commit()
        return str(oid)

    async def test_a_new_outlet_is_locked(self, db, fresh_outlet):
        row = (await db.execute(text(
            "SELECT cashfree_unlocked, payment_prepaid_enabled "
            "FROM outlets WHERE id = :i"), {"i": fresh_outlet})).first()
        assert row[0] is False, "online payment is not activated yet"
        # The owner's PREFERENCE is still on by default — permission is what
        # is absent. Keeping them separate is what lets an admin unlock the
        # outlet later without the owner having to touch anything.
        assert row[1] is True

    async def test_prepaid_is_absent_from_its_resolved_methods(
            self, db, fresh_outlet):
        methods = await CarevoService.payment_methods_for(db, fresh_outlet)
        assert PAY_PREPAID not in methods
        # And with nothing else enabled the list is EMPTY, which is the honest
        # answer: this restaurant has not chosen how to get paid yet.
        assert methods == []

    async def test_an_existing_outlet_was_not_touched(self, db, seed):
        """036 changed a default, not any row. The seeded outlet models an
        established restaurant and keeps online payment."""
        unlocked = await db.scalar(text(
            "SELECT cashfree_unlocked FROM outlets WHERE id = :i"),
            {"i": seed["outlet_id"]})
        assert unlocked is True
        assert PAY_PREPAID in await CarevoService.payment_methods_for(
            db, seed["outlet_id"])

    async def test_an_admin_can_activate_it(self, client, db, seed, fresh_outlet):
        """The intended route out of the locked state."""
        r = await client.patch(
            f"{API}/admin/outlets/{fresh_outlet}/payment-methods",
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "cashfree_unlocked": True})
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_unlocked"] is True
        assert PAY_PREPAID in r.json()["effective_methods"]

    async def test_the_owner_can_take_orders_without_waiting_for_an_admin(
            self, client, db, seed, fresh_outlet):
        """The other route out: the owner turns on a method that needs no
        platform permission at all."""
        # Point the owner's staff account at the new outlet.
        await db.execute(text(
            "UPDATE users SET outlet_id = :o WHERE id = :u"),
            {"o": fresh_outlet, "u": seed["owner_id"]})
        await db.commit()

        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=False, pay_at_pickup=True))
        assert r.status_code == 200, r.text
        assert r.json()["effective_methods"] == [PAY_AT_PICKUP]


class TestSettingsExposeTheLockAndTheResolvedList:
    """AMENDMENT A2: the owner app cannot decide whether to render the Cashfree
    row without both of these, so both are part of the contract."""

    async def test_get_returns_cashfree_unlocked_and_effective_methods(
            self, client, seed):
        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cashfree_unlocked" in body
        assert isinstance(body["cashfree_unlocked"], bool)
        assert "effective_methods" in body
        assert isinstance(body["effective_methods"], list)

    async def test_patch_returns_them_too(self, client, seed):
        """So the app can re-render from the save response without a re-fetch."""
        r = await client.patch(SETTINGS, headers=seed["owner_auth"],
                               json=_body(prepaid=True, pay_at_pickup=True))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "cashfree_unlocked" in body
        assert body["effective_methods"] == [PAY_PREPAID, PAY_AT_PICKUP]

    async def test_the_locked_case_is_distinguishable_from_the_off_case(
            self, client, db, seed):
        """Two different states the app must draw differently: 'you turned it
        off' versus 'we have not activated it'."""
        # Owner turned it off, platform permits it.
        await client.patch(SETTINGS, headers=seed["owner_auth"],
                           json=_body(prepaid=False, pay_at_pickup=True))
        off = (await client.get(SETTINGS, headers=seed["owner_auth"])).json()
        assert off["prepaid"] is False and off["cashfree_unlocked"] is True

        # Platform has not activated it.
        await db.execute(text(
            "UPDATE outlets SET cashfree_unlocked = false WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        locked = (await client.get(SETTINGS, headers=seed["owner_auth"])).json()
        assert locked["cashfree_unlocked"] is False
