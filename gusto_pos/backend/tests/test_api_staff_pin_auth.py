"""PUT /api/v1/staff/{id}/pin — authentication and per-target authorisation.

WHY THIS FILE EXISTS
--------------------
The endpoint was completely unauthenticated, and it is not a secondary "PIN"
field: StaffService.reset_pin (staff/service.py:100) writes
`users.hashed_password`, the credential `/auth/login` checks. Verified end to
end against a live uvicorn before the fix — PUT returned 200 {"ok": true}, the
stored hash stopped verifying the old PIN and started verifying the attacker's
chosen one, and POST /auth/login then issued a real staff JWT. No credential
was needed at any step.

Three gates asserted here:

  401 — no token, or a customer token.
  403 — authenticated staff, but the target is someone else's PIN and the
        caller holds no administering role.
  200 — self-service, and the admin paths (SUPER_ADMIN / Owner / Manager).

The 403-before-404 ordering is deliberate and is asserted: answering 404 for
"exists but not yours" would turn this endpoint into a staff-id enumerator for
any authenticated user.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.security import get_password_hash, verify_password
from app.modules.carevo_customer.deps import create_customer_token
from tests.conftest import API


def _pin_path(staff_id) -> str:
    return f"{API}/staff/{staff_id}/pin"


async def _mk_user(db, *, username: str, pin: str, role: str | None = None,
                   outlet_id=None) -> uuid.UUID:
    """One users row, optionally holding one role. Returns its id."""
    uid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, :h, true, :o, now())
    """), {"i": str(uid), "u": username, "h": get_password_hash(pin),
           "o": str(outlet_id) if outlet_id else None})
    if role:
        rid = await db.scalar(text("SELECT id FROM roles WHERE name = :n"),
                              {"n": role})
        if rid is None:
            rid = await db.scalar(text(
                "INSERT INTO roles (name, permissions, created_at) "
                "VALUES (:n, '{}'::jsonb, now()) RETURNING id"), {"n": role})
        await db.execute(text(
            "INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r) "
            "ON CONFLICT DO NOTHING"), {"u": str(uid), "r": rid})
    await db.commit()
    return uid


async def _hash_of(db, uid) -> str:
    return await db.scalar(
        text("SELECT hashed_password FROM users WHERE id = :i"), {"i": str(uid)})


# --------------------------------- 401 ---------------------------------------

@pytest.mark.asyncio
async def test_no_token_is_401(client, seed):
    r = await client.put(_pin_path(uuid.uuid4()), json={"pin": "4321"})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_customer_token_is_401(client, seed):
    """A customer JWT is not a staff JWT. get_current_staff rejects typ=customer."""
    hdr = {"Authorization": f"Bearer {create_customer_token(seed['customer_id'])}"}
    r = await client.put(_pin_path(uuid.uuid4()), json={"pin": "4321"},
                         headers=hdr)
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_garbage_token_is_401(client, seed):
    r = await client.put(_pin_path(uuid.uuid4()), json={"pin": "4321"},
                         headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_anonymous_cannot_change_a_real_credential(client, seed, db):
    """The actual exploit, asserted dead: the stored hash must not move.

    This is the assertion that matters most in the file — a 401 that still
    wrote would be worthless.
    """
    victim = await _mk_user(db, username=f"victim_{uuid.uuid4().hex[:8]}",
                            pin="1111")
    before = await _hash_of(db, victim)

    r = await client.put(_pin_path(victim), json={"pin": "4321"})
    assert r.status_code == 401, r.text

    after = await _hash_of(db, victim)
    assert after == before, "an unauthenticated request changed the hash"
    assert verify_password("1111", after), "original PIN stopped working"
    assert not verify_password("4321", after), "attacker's PIN now verifies"


# --------------------------------- 403 ---------------------------------------

@pytest.mark.asyncio
async def test_plain_staff_cannot_reset_someone_elses_pin(client, seed, db):
    """403, and the victim's credential is untouched.

    `seed["owner_auth"]` is a staff account holding NO role, which is exactly
    the "authenticated but not privileged" case.
    """
    victim = await _mk_user(db, username=f"victim_{uuid.uuid4().hex[:8]}",
                            pin="1111")
    before = await _hash_of(db, victim)

    r = await client.put(_pin_path(victim), json={"pin": "4321"},
                         headers=seed["owner_auth"])
    assert r.status_code == 403, r.text

    assert await _hash_of(db, victim) == before
    assert verify_password("1111", await _hash_of(db, victim))


@pytest.mark.asyncio
async def test_403_not_404_for_a_nonexistent_target(client, seed):
    """Authorisation is decided BEFORE existence.

    A non-admin must not be able to tell "no such staff id" from "that id
    exists but is not yours" — that difference is a staff-id enumerator.
    """
    r = await client.put(_pin_path(uuid.uuid4()), json={"pin": "4321"},
                         headers=seed["owner_auth"])
    assert r.status_code == 403, (
        f"expected 403 for an unprivileged caller regardless of whether the "
        f"target exists, got {r.status_code}: {r.text}"
    )


# --------------------------------- 200 ---------------------------------------

@pytest.mark.asyncio
async def test_self_service_is_allowed(client, db):
    """Changing your OWN PIN needs no privilege, and really changes it."""
    uname = f"selfserve_{uuid.uuid4().hex[:8]}"
    uid = await _mk_user(db, username=uname, pin="1111")
    hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}

    r = await client.put(_pin_path(uid), json={"pin": "4321"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    after = await _hash_of(db, uid)
    assert verify_password("4321", after), "new PIN does not verify"
    assert not verify_password("1111", after), "old PIN still verifies"


@pytest.mark.asyncio
async def test_super_admin_may_reset_anyone(client, seed, db):
    """seed["admin_auth"] holds SUPER_ADMIN."""
    victim = await _mk_user(db, username=f"victim_{uuid.uuid4().hex[:8]}",
                            pin="1111")
    r = await client.put(_pin_path(victim), json={"pin": "4321"},
                         headers=seed["admin_auth"])
    assert r.status_code == 200, r.text
    assert verify_password("4321", await _hash_of(db, victim))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["Owner", "Manager", "Admin"])
async def test_administering_roles_may_reset_anyone(client, db, role):
    """The roles that run an outlet can reset a subordinate's PIN."""
    actor_name = f"boss_{uuid.uuid4().hex[:8]}"
    await _mk_user(db, username=actor_name, pin="9999", role=role)
    victim = await _mk_user(db, username=f"victim_{uuid.uuid4().hex[:8]}",
                            pin="1111")
    hdr = {"Authorization": f"Bearer {create_access_token(subject=actor_name)}"}

    r = await client.put(_pin_path(victim), json={"pin": "4321"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert verify_password("4321", await _hash_of(db, victim))


@pytest.mark.asyncio
async def test_admin_gets_404_for_a_missing_target(client, seed):
    """An authorised caller DOES get to tell existence apart — that is the
    whole point of the 403-first ordering being conditional on privilege."""
    r = await client.put(_pin_path(uuid.uuid4()), json={"pin": "4321"},
                         headers=seed["admin_auth"])
    assert r.status_code == 404, r.text


# ----------------------------- rehash interaction ----------------------------

@pytest.mark.asyncio
async def test_reset_writes_a_bcrypt_hash(client, db):
    """The PIN written here must be bcrypt, not the old sha256_crypt default."""
    uname = f"selfserve_{uuid.uuid4().hex[:8]}"
    uid = await _mk_user(db, username=uname, pin="1111")
    hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}

    r = await client.put(_pin_path(uid), json={"pin": "4321"}, headers=hdr)
    assert r.status_code == 200, r.text

    after = await _hash_of(db, uid)
    assert after.startswith("$2b$"), f"not a bcrypt hash: {after[:12]}"
