"""The privilege escalation closed by migration 037, and the /users lockdown.

THE ESCALATION, as the review reported it
-----------------------------------------
The owner-settings gate was a DENY-list: refuse WAITER and KITCHEN, allow
everyone else. The justification was that `register_owner` creates the owner's
account with no `user_roles` row, so real owners are role-less and a strict
allow-list would lock them out of their own settings screen.

That held only while nobody else could become role-less. `/api/v1/users` was
mounted with no authorisation at all beyond "be logged in", so:

    1. a WAITER logs in                      (the lowest staff credential)
    2. POST /api/v1/users  with role_ids: [] (a role-less account, their outlet)
    3. log in as it
    4. the deny-list sees no WAITER role     -> not refused
    5. PATCH /pos/outlet/payment-methods     -> owns where the money goes

Step 5 is the whole point. Direct UPI pays the restaurant's VPA with CareVo
never in the path, so an attacker who can set `upi_vpa` redirects customers'
money to themselves and there is no gateway to reverse it.

Two independent fixes, so neither is load-bearing alone:
  * the gate is an ALLOW-list over privileged roles plus the positive
    `users.is_outlet_owner` marker (037) — step 4 now fails; and
  * `/api/v1/users` requires a manager and is scoped to the caller's outlet —
    step 2 now fails.

Every test below is written against the behaviour, not the implementation: each
asserts a status code a caller can observe.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash
from tests.conftest import API

SETTINGS = f"{API}/pos/outlet/payment-methods"
# The collection is mounted at "/" under the prefix, so the trailing slash
# is required — without it Starlette answers 307 and httpx does not follow.
USERS = f"{API}/users/"

ATTACKER_VPA = "attacker@okaxis"


# ------------------------------- helpers -------------------------------------

async def _role_id(db, name: str) -> int:
    rid = await db.scalar(text("SELECT id FROM roles WHERE name = :n"),
                          {"n": name})
    if rid is None:
        rid = await db.scalar(text(
            "INSERT INTO roles (name, permissions, created_at) "
            "VALUES (:n, '{}'::jsonb, now()) RETURNING id"), {"n": name})
        await db.commit()
    return rid


async def _staff(db, outlet_id, role_name: str | None, *, owner_flag=False):
    """A staff account at `outlet_id`, optionally with one role."""
    tag = uuid.uuid4().hex[:8]
    uid = uuid.uuid4()
    username = f"{(role_name or 'norole').lower()}_{tag}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           is_outlet_owner, created_at)
        VALUES (:i, :u, :h, true, :o, :f, now())"""),
        {"i": str(uid), "u": username, "f": owner_flag,
         "h": get_password_hash("correct-horse"),
         "o": str(outlet_id) if outlet_id else None})
    if role_name:
        await db.execute(text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) "
            "ON CONFLICT DO NOTHING"),
            {"u": str(uid), "r": await _role_id(db, role_name)})
    await db.commit()
    return {
        "id": str(uid),
        "username": username,
        "auth": {"Authorization":
                 f"Bearer {create_access_token(subject=username)}"},
    }


async def _second_outlet(db, seed):
    oid = uuid.uuid4()
    org = await db.scalar(text(
        "SELECT organization_id FROM outlets WHERE id = :o"),
        {"o": seed["outlet_id"]})
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city,
                             is_visible, upi_id, geofence_radius_meters,
                             verification_status, created_at)
        VALUES (:i,:o,:n,'T', true, 'x@upi', 150, 'active', now())"""),
        {"i": str(oid), "o": str(org), "n": f"Other {uuid.uuid4().hex[:8]}"})
    await db.commit()
    return str(oid)


# ===================== 1. the escalation, step by step =======================

class TestTheFiveStepEscalation:
    """Walked exactly as reported. It must fail, and this records WHERE."""

    async def test_the_escalation_fails(self, client, db, seed):
        # Step 1 — a waiter logs in. This still works; waiters are real staff.
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        probe = await client.get(f"{API}/pos/orders",
                                 headers=waiter["auth"])
        assert probe.status_code != 401, \
            "precondition: the waiter's credential is valid"

        # Step 2 — mint a role-less account. THE FIRST FIX: /users is no longer
        # open to any logged-in staff member.
        mint = await client.post(USERS, headers=waiter["auth"], json={
            "username": f"mole_{uuid.uuid4().hex[:8]}",
            "password": "correct-horse",
            "outlet_id": seed["outlet_id"],
            "role_ids": [],
        })
        assert mint.status_code == 403, \
            f"step 2 must be refused, got {mint.status_code}: {mint.text}"

        # Steps 3+4 — suppose the attacker got a role-less account anyway (an
        # older account, a seeded row, a future route). THE SECOND FIX: the
        # gate no longer infers ownership from the ABSENCE of a role.
        mole = await _staff(db, seed["outlet_id"], None)
        assert await db.scalar(text(
            "SELECT count(*) FROM user_roles WHERE user_id = :u"),
            {"u": mole["id"]}) == 0
        assert await db.scalar(text(
            "SELECT is_outlet_owner FROM users WHERE id = :u"),
            {"u": mole["id"]}) is False

        read = await client.get(SETTINGS, headers=mole["auth"])
        assert read.status_code == 403, \
            f"step 4 must be refused, got {read.status_code}: {read.text}"

        # Step 5 — THE PAYLOAD. Redirecting the VPA is what the escalation was
        # worth, so it is asserted on the DATABASE as well as the status code.
        before = await db.scalar(text(
            "SELECT upi_vpa FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        steal = await client.patch(SETTINGS, headers=mole["auth"], json={
            "prepaid": False, "pay_at_pickup": False, "upi_manual": True,
            "upi_vpa": ATTACKER_VPA, "upi_payee_name": "Not The Restaurant",
            "upi_attested": True,
        })
        assert steal.status_code == 403, \
            f"step 5 must be refused, got {steal.status_code}: {steal.text}"

        await db.rollback()          # drop the session's snapshot, re-read
        after = await db.scalar(text(
            "SELECT upi_vpa FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        assert after == before, "the payee VPA must be untouched"
        assert after != ATTACKER_VPA

    async def test_a_waiter_cannot_mint_an_owner_flagged_account(
            self, client, db, seed):
        """The flag must not be settable through the account-creation body, or
        037 just moves the escalation one field over."""
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        name = f"mole_{uuid.uuid4().hex[:8]}"
        r = await client.post(USERS, headers=waiter["auth"], json={
            "username": name, "password": "correct-horse",
            "outlet_id": seed["outlet_id"], "role_ids": [],
            "is_outlet_owner": True,
        })
        assert r.status_code == 403, r.text
        assert await db.scalar(text(
            "SELECT count(*) FROM users WHERE username = :u"),
            {"u": name}) == 0

    async def test_even_a_manager_cannot_mint_an_owner_flagged_account(
            self, client, db, seed):
        """A manager MAY add staff. They may not promote one to owner, which
        would hand over the payment settings they are only a guest in."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        name = f"promoted_{uuid.uuid4().hex[:8]}"
        r = await client.post(USERS, headers=mgr["auth"], json={
            "username": name, "password": "correct-horse",
            "outlet_id": seed["outlet_id"], "role_ids": [],
            "is_outlet_owner": True,
        })
        # Refused outright, or accepted with the field IGNORED — either is
        # sound, a silently-honoured flag is not.
        if r.status_code == 200:
            assert await db.scalar(text(
                "SELECT is_outlet_owner FROM users WHERE username = :u"),
                {"u": name}) is False, \
                "is_outlet_owner must never be settable over the wire"
        else:
            assert r.status_code in (403, 422), r.text


# ===================== 2. the gate's allow-list ==============================

class TestTheGate:
    async def test_a_role_less_unflagged_account_is_refused(
            self, client, db, seed):
        who = await _staff(db, seed["outlet_id"], None)
        assert (await client.get(SETTINGS,
                                 headers=who["auth"])).status_code == 403

    async def test_a_flagged_owner_is_allowed(self, client, db, seed):
        """The positive marker, with no role at all — what register_owner now
        produces, and the reason the allow-list does not lock owners out."""
        who = await _staff(db, seed["outlet_id"], None, owner_flag=True)
        r = await client.get(SETTINGS, headers=who["auth"])
        assert r.status_code == 200, r.text
        assert r.json()["outlet_id"] == seed["outlet_id"]

    @pytest.mark.parametrize("role", ["Owner", "Manager", "Admin"])
    async def test_privileged_roles_are_allowed(self, client, db, seed, role):
        who = await _staff(db, seed["outlet_id"], role)
        assert (await client.get(SETTINGS,
                                 headers=who["auth"])).status_code == 200

    @pytest.mark.parametrize("role", ["Waiter", "Kitchen", "Cashier", "Chef"])
    async def test_unprivileged_roles_are_refused(self, client, db, seed, role):
        """An allow-list refuses roles it has never heard of — the deny-list
        admitted every one of these except the two it was told about."""
        who = await _staff(db, seed["outlet_id"], role)
        assert (await client.get(SETTINGS,
                                 headers=who["auth"])).status_code == 403
        assert (await client.patch(
            SETTINGS, headers=who["auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "upi_manual": False})).status_code == 403


# ===================== 3. /api/v1/users is locked ============================

class TestUsersRouteIsLocked:
    async def test_a_waiter_cannot_list_staff(self, client, db, seed):
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        assert (await client.get(USERS,
                                 headers=waiter["auth"])).status_code == 403

    async def test_a_waiter_cannot_edit_their_own_roles(
            self, client, db, seed):
        """Self-promotion: if a waiter can PATCH their own role_ids they do not
        need a second account at all."""
        waiter = await _staff(db, seed["outlet_id"], "Waiter")
        owner_role = await _role_id(db, "Owner")

        r = await client.put(f"{USERS}{waiter['id']}",
                             headers=waiter["auth"],
                             json={"role_ids": [owner_role]})
        assert r.status_code == 403, r.text

        await db.rollback()
        names = (await db.execute(text("""
            SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id
             WHERE ur.user_id = :u"""), {"u": waiter["id"]})).fetchall()
        assert [n.name for n in names] == ["Waiter"], \
            "the waiter's roles must be unchanged"

        # And the settings screen is still shut to them afterwards.
        assert (await client.get(SETTINGS,
                                 headers=waiter["auth"])).status_code == 403

    async def test_a_manager_cannot_edit_their_own_roles_either(
            self, client, db, seed):
        """Privileged fields are refused for EVERYONE, including a caller who
        is otherwise allowed to manage staff."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        r = await client.put(f"{USERS}{mgr['id']}", headers=mgr["auth"],
                             json={"role_ids": [await _role_id(db, "Owner")]})
        assert r.status_code == 403, r.text

    async def test_a_manager_cannot_move_a_user_to_another_outlet(
            self, client, db, seed):
        """outlet_id is privileged for the same reason role_ids is: it decides
        whose payment settings the account is measured against."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        victim = await _staff(db, seed["outlet_id"], "Waiter")
        other = await _second_outlet(db, seed)

        r = await client.put(f"{USERS}{victim['id']}", headers=mgr["auth"],
                             json={"outlet_id": other})
        assert r.status_code == 403, r.text

        await db.rollback()
        assert str(await db.scalar(text(
            "SELECT outlet_id FROM users WHERE id = :u"),
            {"u": victim["id"]})) == seed["outlet_id"]

    async def test_a_manager_cannot_create_a_user_at_another_outlet(
            self, client, db, seed):
        """Cross-outlet POST: a manager at A must not seed accounts into B."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        other = await _second_outlet(db, seed)
        name = f"foreign_{uuid.uuid4().hex[:8]}"

        r = await client.post(USERS, headers=mgr["auth"], json={
            "username": name, "password": "correct-horse",
            "outlet_id": other, "role_ids": [],
        })
        assert r.status_code in (403, 404), r.text

        await db.rollback()
        assert await db.scalar(text(
            "SELECT count(*) FROM users WHERE username = :u"),
            {"u": name}) == 0

    async def test_a_manager_cannot_touch_a_user_at_another_outlet(
            self, client, db, seed):
        """And cannot reach sideways to an existing account either."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        other = await _second_outlet(db, seed)
        foreign = await _staff(db, other, "Waiter")

        # Lambdas, not coroutines: a tuple of coroutines would leave the
        # later ones unawaited when an earlier assertion fails.
        for call in (
            lambda: client.get(f"{USERS}{foreign['id']}", headers=mgr["auth"]),
            lambda: client.put(f"{USERS}{foreign['id']}", headers=mgr["auth"],
                               json={"username": "renamed"}),
            lambda: client.delete(f"{USERS}{foreign['id']}",
                                  headers=mgr["auth"]),
        ):
            r = await call()
            assert r.status_code in (403, 404), r.text

        await db.rollback()
        assert await db.scalar(text(
            "SELECT count(*) FROM users WHERE id = :u"),
            {"u": foreign["id"]}) == 1

    async def test_the_list_is_scoped_to_the_callers_outlet(
            self, client, db, seed):
        """A manager at A reading the roster must not learn B's usernames —
        those are the login names for an outlet they have no business in."""
        mgr = await _staff(db, seed["outlet_id"], "Manager")
        other = await _second_outlet(db, seed)
        foreign = await _staff(db, other, "Waiter")

        r = await client.get(USERS, headers=mgr["auth"])
        assert r.status_code == 200, r.text
        names = [u["username"] for u in r.json()]
        assert mgr["username"] in names
        assert foreign["username"] not in names, \
            "the roster leaked another outlet's accounts"

    async def test_a_super_admin_still_has_the_route(self, client, seed):
        """The lockdown must not take the platform's own tooling away."""
        r = await client.get(USERS, headers=seed["admin_auth"])
        assert r.status_code == 200, r.text

    async def test_a_super_admin_cannot_edit_their_own_roles(
            self, client, db, seed):
        """Not even here. Self-edit of privilege is refused unconditionally, so
        a stolen admin session cannot entrench itself."""
        uid = await db.scalar(text("SELECT id FROM users WHERE username = :u"),
                              {"u": seed["admin_username"]})
        r = await client.put(f"{USERS}{uid}", headers=seed["admin_auth"],
                             json={"role_ids": [await _role_id(db, "Owner")]})
        assert r.status_code == 403, r.text
