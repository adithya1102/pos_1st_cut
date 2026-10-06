"""bcrypt, with legacy hashes migrated on the way past.

The context used to be CryptContext(schemes=["sha256_crypt", "md5_crypt"]).
passlib hashes with the FIRST scheme, so every password and every staff PIN
this codebase wrote was sha256_crypt, and md5_crypt still verified. Both are
fast by design; against a 4-digit PIN — which is exactly what
StaffService.create_staff stores — the whole 10,000-value keyspace is
exhaustible on a stolen hash, and the production DSN was committed to a public
repository, so "stolen hash" was not a hypothetical.

Three things are pinned here:

  1. new hashes are bcrypt;
  2. an existing sha256_crypt login still works AND is rewritten to bcrypt on
     the way through, because that is the only moment the plaintext exists;
  3. md5_crypt is gone — not deprecated, not slow, rejected.
"""
import pytest
from passlib.context import CryptContext
from sqlalchemy import text

from app.core.security import (
    get_password_hash,
    pwd_context,
    verify_and_rehash,
    verify_password,
)
from tests.conftest import API

# Contexts that can still MINT legacy hashes, so the tests can construct the
# rows a real database would be carrying. Deliberately separate from the app's
# context, which can no longer produce either of these.
_SHA = CryptContext(schemes=["sha256_crypt"])
_MD5 = CryptContext(schemes=["md5_crypt"])


# --------------------------------------------------------------------------
# The context itself
# --------------------------------------------------------------------------
def test_new_hashes_are_bcrypt():
    h = get_password_hash("correct horse battery staple")
    assert h.startswith(("$2a$", "$2b$", "$2y$")), f"not a bcrypt hash: {h[:8]}"
    assert pwd_context.identify(h) == "bcrypt"


def test_bcrypt_roundtrip():
    h = get_password_hash("hunter2")
    assert verify_password("hunter2", h) is True
    assert verify_password("hunter3", h) is False


def test_sha256_still_verifies_but_is_flagged_stale():
    """Legacy rows must keep working — locking out every existing staff member
    is not an acceptable way to improve a hash."""
    legacy = _SHA.hash("hunter2")
    assert verify_password("hunter2", legacy) is True
    assert pwd_context.needs_update(legacy) is True


def test_md5_is_rejected_outright():
    """Dropped, not deprecated. An md5 hash must not authenticate at any cost."""
    legacy = _MD5.hash("hunter2")
    assert verify_password("hunter2", legacy) is False


def test_a_corrupt_hash_is_a_failed_login_not_a_crash():
    for junk in ("", "not-a-hash", "$9z$nonsense", "x" * 200):
        assert verify_password("hunter2", junk) is False


# --------------------------------------------------------------------------
# verify_and_rehash
# --------------------------------------------------------------------------
def test_rehash_upgrades_a_legacy_hash():
    legacy = _SHA.hash("hunter2")
    ok, new_hash = verify_and_rehash("hunter2", legacy)
    assert ok is True
    assert new_hash is not None, "a sha256 hash must be handed back as bcrypt"
    assert pwd_context.identify(new_hash) == "bcrypt"
    # The replacement must actually work, or login breaks on the NEXT attempt
    # rather than this one — the worst possible time to find out.
    assert verify_password("hunter2", new_hash) is True


def test_rehash_is_a_no_op_for_a_current_bcrypt_hash():
    ok, new_hash = verify_and_rehash("hunter2", get_password_hash("hunter2"))
    assert ok is True
    assert new_hash is None, "no rewrite should be offered when nothing changed"


def test_rehash_offers_nothing_on_a_wrong_password():
    ok, new_hash = verify_and_rehash("wrong", _SHA.hash("hunter2"))
    assert (ok, new_hash) == (False, None)


def test_rehash_declines_md5_entirely():
    ok, new_hash = verify_and_rehash("hunter2", _MD5.hash("hunter2"))
    assert (ok, new_hash) == (False, None), \
        "an md5 hash must not be upgraded — it must not authenticate at all"


# --------------------------------------------------------------------------
# End to end: the upgrade actually lands in the database
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_password_login_migrates_the_stored_hash(client, seed, db):
    """A staff member whose row holds sha256_crypt logs in, and the row is
    bcrypt afterwards. This is the whole point of the change: without it every
    legacy row stays on the weak algorithm forever."""
    username = seed["owner_username"]
    await db.execute(
        text("UPDATE users SET hashed_password = :h WHERE username = :u"),
        {"h": _SHA.hash("legacy-pw"), "u": username},
    )
    await db.commit()

    before = await db.execute(
        text("SELECT hashed_password FROM users WHERE username = :u"), {"u": username})
    assert pwd_context.identify(before.scalar_one()) == "sha256_crypt"

    r = await client.post(
        f"{API}/auth/login",
        data={"username": username, "password": "legacy-pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

    after = await db.execute(
        text("SELECT hashed_password FROM users WHERE username = :u"), {"u": username})
    stored = after.scalar_one()
    assert pwd_context.identify(stored) == "bcrypt", \
        "the login succeeded but the legacy hash was left in place"
    assert verify_password("legacy-pw", stored) is True


@pytest.mark.asyncio
async def test_a_wrong_password_does_not_rewrite_the_hash(client, seed, db):
    username = seed["owner_username"]
    legacy = _SHA.hash("legacy-pw")
    await db.execute(
        text("UPDATE users SET hashed_password = :h WHERE username = :u"),
        {"h": legacy, "u": username},
    )
    await db.commit()

    r = await client.post(
        f"{API}/auth/login",
        data={"username": username, "password": "not-the-password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401

    after = await db.execute(
        text("SELECT hashed_password FROM users WHERE username = :u"), {"u": username})
    assert after.scalar_one() == legacy, "a failed login must not touch the row"


@pytest.mark.asyncio
async def test_an_md5_row_can_no_longer_log_in(client, seed, db):
    """The operational consequence of dropping md5, asserted rather than
    discovered. Such an account needs a password reset."""
    username = seed["owner_username"]
    await db.execute(
        text("UPDATE users SET hashed_password = :h WHERE username = :u"),
        {"h": _MD5.hash("legacy-pw"), "u": username},
    )
    await db.commit()

    r = await client.post(
        f"{API}/auth/login",
        data={"username": username, "password": "legacy-pw"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401, "an md5 hash authenticated — it must not"
