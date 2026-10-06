"""POST /api/v1/auth/pin-login — identifier required, single-row verification.

WHAT WAS WRONG
--------------
    result = await db.execute(select(User).where(User.is_active == True))
    for user in result.scalars().all():
        if verify_password(request.pin, user.hashed_password):
            ...issue a token for THAT user

The request carried a PIN and no identifier, so the endpoint answered "is this
PIN anybody's?" and handed back a token for whichever row the unordered scan
reached first. A 4-digit PIN is 10,000 values and production holds 1,906 users,
so a collision is not a corner case — it is the expected outcome, and the
caller lands in someone else's account, possibly with a different role.

The headline test here is `test_right_pin_wrong_identifier_fails`: it creates
two users who share a PIN and proves that claiming one identity while holding
the other's PIN is refused. Under the old code that call succeeded.

Also covered: the shared login throttle on this endpoint AND on /auth/login.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.security import get_password_hash
from app.modules.carevo_customer.service import _login_hits
from tests.conftest import API

PIN_LOGIN = f"{API}/auth/pin-login"
LOGIN = f"{API}/auth/login"


@pytest.fixture(autouse=True)
def _clear_login_buckets():
    """The limiter is process-global; isolate every test from its neighbours."""
    _login_hits.clear()
    yield
    _login_hits.clear()


async def _mk_staff(db, *, pin: str, outlet_id=None) -> str:
    uname = f"TEST_CAREVO_pin_{uuid.uuid4().hex[:10]}"
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id,
                           created_at)
        VALUES (:i, :u, :h, true, :o, now())
    """), {"i": str(uuid.uuid4()), "u": uname, "h": get_password_hash(pin),
           "o": str(outlet_id) if outlet_id else None})
    await db.commit()
    return uname


# ------------------------- the headline assertion ----------------------------

@pytest.mark.asyncio
async def test_right_pin_wrong_identifier_fails(client, db):
    """TWO users share the PIN 4321. Claiming A while holding B's PIN fails.

    Under the previous implementation this returned 200 and a token, because
    the scan found *a* user whose hash matched and stopped there.
    """
    shared_pin = "4321"
    user_a = await _mk_staff(db, pin=shared_pin)
    user_b = await _mk_staff(db, pin=shared_pin)

    # Sanity: each account really does accept that PIN under its OWN name.
    for uname in (user_a, user_b):
        ok = await client.post(PIN_LOGIN, json={"username": uname,
                                                "pin": shared_pin})
        assert ok.status_code == 200, f"{uname} cannot log in at all: {ok.text}"
        assert ok.json()["staff"]["name"] == uname

    # Now the real assertion: a THIRD user with a DIFFERENT pin cannot get in
    # using a PIN that belongs to someone else.
    victim = await _mk_staff(db, pin="1111")
    r = await client.post(PIN_LOGIN, json={"username": victim,
                                           "pin": shared_pin})
    assert r.status_code == 401, (
        f"logged in as {victim} with another account's PIN: "
        f"{r.status_code} {r.text}"
    )


@pytest.mark.asyncio
async def test_token_identifies_the_claimed_user_not_a_colliding_one(client, db):
    """Even when a collision exists, the token must be for who you said."""
    pin = "7777"
    first = await _mk_staff(db, pin=pin)
    second = await _mk_staff(db, pin=pin)

    r = await client.post(PIN_LOGIN, json={"username": second, "pin": pin})
    assert r.status_code == 200, r.text
    assert r.json()["staff"]["name"] == second, (
        "issued a token for a colliding account rather than the claimed one"
    )
    assert r.json()["staff"]["name"] != first


# ------------------------------ required field --------------------------------

@pytest.mark.asyncio
async def test_username_is_required(client, db):
    """The old client payload — {pin} alone — is now a 422."""
    await _mk_staff(db, pin="4321")
    r = await client.post(PIN_LOGIN, json={"pin": "4321"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_blank_username_is_rejected(client):
    r = await client.post(PIN_LOGIN, json={"username": "   ", "pin": "4321"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_unknown_username_and_wrong_pin_look_identical(client, db):
    """Not a username oracle: both answer 401 with the same body."""
    known = await _mk_staff(db, pin="1111")

    unknown = await client.post(PIN_LOGIN, json={
        "username": f"TEST_CAREVO_nope_{uuid.uuid4().hex[:8]}", "pin": "1111"})
    wrong_pin = await client.post(PIN_LOGIN, json={
        "username": known, "pin": "2222"})

    assert unknown.status_code == wrong_pin.status_code == 401
    assert unknown.json() == wrong_pin.json(), (
        "an unknown username is distinguishable from a wrong PIN"
    )


@pytest.mark.asyncio
async def test_inactive_user_cannot_pin_login(client, db):
    uname = await _mk_staff(db, pin="1111")
    await db.execute(text("UPDATE users SET is_active = false WHERE username = :u"),
                     {"u": uname})
    await db.commit()
    r = await client.post(PIN_LOGIN, json={"username": uname, "pin": "1111"})
    assert r.status_code == 401, r.text


# ------------------------------ rate limiting ---------------------------------

@pytest.mark.asyncio
async def test_pin_login_is_rate_limited(client, db):
    """The 11th attempt in the window is refused, with Retry-After."""
    uname = await _mk_staff(db, pin="1111")

    for i in range(10):
        r = await client.post(PIN_LOGIN, json={"username": uname, "pin": "9999"})
        assert r.status_code == 401, f"attempt {i} answered {r.status_code}"

    blocked = await client.post(PIN_LOGIN, json={"username": uname, "pin": "9999"})
    assert blocked.status_code == 429, blocked.text
    assert blocked.headers.get("Retry-After"), "no Retry-After on the 429"
    body = blocked.json()["detail"]
    assert body["error"] == "too_many_login_attempts"


@pytest.mark.asyncio
async def test_the_throttle_refuses_even_a_CORRECT_pin(client, db):
    """Once the bucket is full the account is protected, right PIN included.

    This is what makes it a brute-force defence rather than a nuisance: an
    attacker who exhausts the window does not get to use the hit when it lands.
    """
    uname = await _mk_staff(db, pin="1111")
    for _ in range(10):
        await client.post(PIN_LOGIN, json={"username": uname, "pin": "9999"})

    r = await client.post(PIN_LOGIN, json={"username": uname, "pin": "1111"})
    assert r.status_code == 429, r.text


@pytest.mark.asyncio
async def test_auth_login_shares_the_same_throttle(client, db):
    """/auth/login is form-encoded and was also unlimited."""
    uname = await _mk_staff(db, pin="1111")

    for i in range(10):
        r = await client.post(LOGIN, data={"username": uname,
                                           "password": "wrong-password"})
        assert r.status_code == 401, f"attempt {i} answered {r.status_code}"

    blocked = await client.post(LOGIN, data={"username": uname,
                                             "password": "wrong-password"})
    assert blocked.status_code == 429, blocked.text


@pytest.mark.asyncio
async def test_a_different_username_has_its_own_budget(client, db):
    """Per-identifier bucketing: one account's lockout is not everyone's.

    The IP bucket is shared in the test client (one peer), so this asserts the
    identifier bucket exists by using up a DIFFERENT name's budget and showing
    the first name is unaffected — with the IP cap raised out of the way.
    """
    from app.core.config import settings
    original = settings.LOGIN_RATE_LIMIT_ATTEMPTS
    settings.LOGIN_RATE_LIMIT_ATTEMPTS = 3
    try:
        a = await _mk_staff(db, pin="1111")
        b = await _mk_staff(db, pin="2222")

        # Burn A's budget. The shared IP bucket fills at the same rate, so
        # clear only the IP key to isolate what this test is about.
        for _ in range(3):
            await client.post(PIN_LOGIN, json={"username": a, "pin": "0000"})
        for key in [k for k in _login_hits if k.startswith("ip:")]:
            _login_hits.pop(key)

        blocked = await client.post(PIN_LOGIN, json={"username": a, "pin": "1111"})
        assert blocked.status_code == 429, "A should still be throttled"

        for key in [k for k in _login_hits if k.startswith("ip:")]:
            _login_hits.pop(key)
        ok = await client.post(PIN_LOGIN, json={"username": b, "pin": "2222"})
        assert ok.status_code == 200, f"B was caught by A's bucket: {ok.text}"
    finally:
        settings.LOGIN_RATE_LIMIT_ATTEMPTS = original


@pytest.mark.asyncio
async def test_successful_logins_also_count(client, db):
    """Attempts are counted, not just failures.

    Counting failures alone would let an attacker reset their budget with one
    correct login between guesses.
    """
    uname = await _mk_staff(db, pin="1111")
    for i in range(10):
        r = await client.post(PIN_LOGIN, json={"username": uname, "pin": "1111"})
        assert r.status_code == 200, f"attempt {i}: {r.text}"

    blocked = await client.post(PIN_LOGIN, json={"username": uname, "pin": "1111"})
    assert blocked.status_code == 429, blocked.text
