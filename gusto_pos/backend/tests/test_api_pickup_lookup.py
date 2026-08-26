"""Owner-side pickup by code: find the order, then confirm the handover.

Staff at the counter have the code the customer is showing them and nothing
else — no order id. `POST /pos/orders/lookup-pickup` turns that code into the
order so they can check it against the bag; `POST /pos/orders/verify-pickup`
closes it. They are two calls on purpose, and the split is what most of these
tests pin: a code that merely MATCHES must not complete anything.

The other line held here is outlet scoping. Both routes take the outlet from
the caller's own staff account, never from the request, so one restaurant
cannot reach another's orders whatever it types. verify-pickup did not do this
until now — it resolved the order id from the body unscoped, so any staff
account could complete any outlet's order. test_verify_pickup_rejects_another
_outlets_order is the regression test for that.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.security import get_password_hash

API = "/api/v1"

pytestmark = pytest.mark.asyncio


async def _code_for(db, order_id: str) -> str:
    code = await db.scalar(
        text("SELECT pickup_code FROM customer_orders WHERE id = :i"),
        {"i": order_id},
    )
    assert code, "a PAID order should carry a pickup code"
    return code


async def _status_of(db, order_id: str) -> str:
    return await db.scalar(
        text("SELECT status FROM customer_orders WHERE id = :i"), {"i": order_id}
    )


@pytest.fixture(autouse=True)
def _reset_pickup_miss_limit():
    """Pickup misses are capped per outlet by an in-process dict.

    `seed` builds a fresh outlet per test so counters cannot leak between them
    today, but that is a property of a fixture rather than of this limiter —
    clearing it explicitly means a future change to seed's scope shows up as
    the fixture change it is, not as an unrelated 429 in someone else's test.
    """
    from app.modules.carevo_customer import service as svc

    svc._pickup_miss_hits.clear()
    yield
    svc._pickup_miss_hits.clear()


@pytest_asyncio.fixture
async def rival(db):
    """A second restaurant with its own staff login.

    Deliberately a whole separate org/outlet rather than another user on the
    same outlet: the thing under test is the boundary between restaurants.
    """
    tag = uuid.uuid4().hex[:8]
    org_id, outlet_id, staff_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(
        text("INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
        {"i": str(org_id), "n": f"TEST_CAREVO_RivalOrg {tag}"},
    )
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             upi_id, geofence_radius_meters, verification_status,
                             created_at)
        VALUES (:i,:o,:n,'Testville', true, 'rival@upi', 150, 'active', now())"""),
        {"i": str(outlet_id), "o": str(org_id), "n": f"TEST_CAREVO_RivalOutlet {tag}"})
    await db.execute(text("""
        INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)
        VALUES (:i,:u,:h, true, :o, now())"""),
        {"i": str(staff_id), "u": f"rival_{tag}",
         "h": get_password_hash("correct-horse"), "o": str(outlet_id)})
    await db.commit()
    return {
        "outlet_id": str(outlet_id),
        "auth": {"Authorization": f"Bearer {create_access_token(subject=f'rival_{tag}')}"},
    }


# --------------------------------------------------------------------------
# finding the order
# --------------------------------------------------------------------------
async def test_correct_code_finds_the_order_and_its_items(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["owner_auth"], json={"pickup_code": code})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["found"] is True
    assert str(body["order"]["order_id"]) == order_id
    # The items are the point: they are what staff check the bag against.
    items = body["order"]["items"]
    assert len(items) == 1
    assert items[0]["quantity"] == 2
    assert items[0]["name"]


async def test_the_code_is_matched_case_insensitively_and_untrimmed(
    client, seed, paid_order, db
):
    """Staff retype what they see; a stray space must not read as 'not found'."""
    code = await _code_for(db, str(paid_order["id"]))

    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["owner_auth"],
                          json={"pickup_code": f"  {code.lower()} "})
    assert r.status_code == 200, r.text
    assert r.json()["found"] is True


async def test_wrong_code_is_a_clean_miss_not_an_error(client, seed, paid_order):
    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["owner_auth"], json={"pickup_code": "999999"})
    # 200 + found:false, NOT 404 — the app has to tell "no such code" apart
    # from "the request failed", and a 404 also means route/network trouble.
    assert r.status_code == 200, r.text
    assert r.json()["found"] is False
    assert r.json().get("order") is None


async def test_lookup_requires_staff_auth(client, seed, paid_order, db):
    code = await _code_for(db, str(paid_order["id"]))
    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["customer_auth"], json={"pickup_code": code})
    assert r.status_code in (401, 403), r.text

    anon = await client.post(f"{API}/pos/orders/lookup-pickup",
                             json={"pickup_code": code})
    assert anon.status_code in (401, 403), anon.text


# --------------------------------------------------------------------------
# the outlet boundary
# --------------------------------------------------------------------------
async def test_another_outlets_code_never_matches(
    client, seed, paid_order, rival, db
):
    """The hard requirement: a rival restaurant cannot find this order.

    The code is real and the order is live — the ONLY reason this misses is
    that the lookup is scoped to the caller's own outlet.
    """
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=rival["auth"], json={"pickup_code": code})
    assert r.status_code == 200, r.text
    assert r.json()["found"] is False, "a rival outlet must not resolve this code"

    # And the order is untouched by the attempt.
    assert await _status_of(db, order_id) == "PAID"


async def test_verify_pickup_rejects_another_outlets_order(
    client, seed, paid_order, rival, db
):
    """Regression: verify-pickup used to resolve the order id unscoped.

    With the correct code AND the real order id, a staff account belonging to
    a different outlet could complete the order. It must now 404 and leave the
    order exactly as it was.
    """
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    r = await client.post(f"{API}/pos/orders/verify-pickup",
                          headers=rival["auth"],
                          json={"order_id": order_id, "pickup_code": code})
    assert r.status_code == 404, (
        f"another outlet completed this order — expected 404, got {r.status_code}: {r.text}"
    )
    assert await _status_of(db, order_id) == "PAID", (
        "the order must be untouched after a cross-outlet attempt"
    )


# --------------------------------------------------------------------------
# lookup does not complete; confirm does
# --------------------------------------------------------------------------
async def test_lookup_alone_does_not_complete_the_order(
    client, seed, paid_order, db
):
    """Entering the code is not the handover. The confirm tap is."""
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    for _ in range(3):
        r = await client.post(f"{API}/pos/orders/lookup-pickup",
                              headers=seed["owner_auth"], json={"pickup_code": code})
        assert r.json()["found"] is True

    assert await _status_of(db, order_id) == "PAID", (
        "looking an order up must never close it, however many times"
    )
    # Nor may a read-only lookup burn the order's verify attempts.
    attempts = await db.scalar(
        text("SELECT failed_attempts FROM customer_orders WHERE id = :i"),
        {"i": order_id},
    )
    assert (attempts or 0) == 0


async def test_confirm_after_lookup_completes_the_order(
    client, seed, paid_order, db
):
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    found = await client.post(f"{API}/pos/orders/lookup-pickup",
                              headers=seed["owner_auth"], json={"pickup_code": code})
    assert found.json()["found"] is True
    assert await _status_of(db, order_id) == "PAID"

    # Same endpoint and same transition the per-order verify box already used.
    r = await client.post(f"{API}/pos/orders/verify-pickup",
                          headers=seed["owner_auth"],
                          json={"order_id": order_id, "pickup_code": code})
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    assert r.json()["status"] == "COMPLETED"

    assert await _status_of(db, order_id) == "COMPLETED"
    verified_at = await db.scalar(
        text("SELECT pickup_verified_at FROM customer_orders WHERE id = :i"),
        {"i": order_id},
    )
    assert verified_at is not None


async def test_a_collected_order_stops_matching(client, seed, paid_order, db):
    """Only currently-pending orders match — the same scope the code's own
    uniqueness is guaranteed within, so a reissued code cannot collide with a
    closed order's."""
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    await client.post(f"{API}/pos/orders/verify-pickup",
                      headers=seed["owner_auth"],
                      json={"order_id": order_id, "pickup_code": code})
    assert await _status_of(db, order_id) == "COMPLETED"

    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["owner_auth"], json={"pickup_code": code})
    assert r.json()["found"] is False


async def test_an_unpaid_order_has_no_code_to_find(client, seed, db):
    """Codes are issued at payment. Before that there is nothing to look up."""
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
        "outlet_id": seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
    })
    assert r.status_code == 200, r.text
    code = await db.scalar(
        text("SELECT pickup_code FROM customer_orders WHERE id = :i"),
        {"i": str(r.json()["id"])},
    )
    assert code is None


async def test_a_locked_order_is_found_but_flagged(client, seed, paid_order, db):
    """Lookup must not become a way round the 3-attempt lockout.

    The order still comes back — staff need to see WHICH order is stuck — but
    it is marked locked so the app shows the lockout instead of a confirm
    button the server would refuse anyway.
    """
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)
    await db.execute(
        text("UPDATE customer_orders SET is_locked = true WHERE id = :i"),
        {"i": order_id},
    )
    await db.commit()

    r = await client.post(f"{API}/pos/orders/lookup-pickup",
                          headers=seed["owner_auth"], json={"pickup_code": code})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["locked"] is True

    # And confirming it is still refused.
    v = await client.post(f"{API}/pos/orders/verify-pickup",
                          headers=seed["owner_auth"],
                          json={"order_id": order_id, "pickup_code": code})
    assert v.status_code == 423, v.text
    assert await _status_of(db, order_id) == "PAID"


# --------------------------------------------------------------------------
# the per-outlet miss cap
#
# The per-order 3-strike lockout only counts attempts against an order that
# was already resolved. A miss resolves nothing, so it used to cost the caller
# nothing and could be repeated without limit against an 8^6 code space. These
# pin the cap that closes that, and — just as importantly — pin that it does
# not fire at staff doing ordinary work.
# --------------------------------------------------------------------------
async def _miss(client, auth, code="999999"):
    return await client.post(f"{API}/pos/orders/lookup-pickup",
                             headers=auth, json={"pickup_code": code})


async def test_repeated_wrong_codes_trip_the_outlet_cap(client, seed, paid_order):
    limit = settings.PICKUP_MISS_LIMIT

    for i in range(limit):
        r = await _miss(client, seed["owner_auth"], code=f"99999{i % 10}")
        assert r.status_code == 200, f"miss {i + 1} should still be served: {r.text}"
        assert r.json()["found"] is False

    blocked = await _miss(client, seed["owner_auth"])
    assert blocked.status_code == 429, (
        f"attempt {limit + 1} should be refused, got {blocked.status_code}: {blocked.text}"
    )


async def test_the_429_says_how_long_to_wait(client, seed, paid_order):
    """A silent failure would look identical to 'no such code' at the counter."""
    for _ in range(settings.PICKUP_MISS_LIMIT):
        await _miss(client, seed["owner_auth"])

    r = await _miss(client, seed["owner_auth"])
    assert r.status_code == 429

    # Retry-After is the standard header; clients that know nothing about our
    # payload shape still get a usable hint from it.
    assert "retry-after" in {k.lower() for k in r.headers}
    hint = int(r.headers["retry-after"])
    assert 0 < hint <= settings.PICKUP_MISS_WINDOW_SECONDS

    detail = r.json()["detail"]
    assert detail["error"] == "too_many_pickup_attempts"
    assert detail["retry_after_seconds"] == hint
    assert str(hint) in detail["message"]


async def test_a_found_code_clears_the_run_of_misses(
    client, seed, paid_order, db
):
    """Successes must not count toward the cap — and must reset it.

    The limit is on CONSECUTIVE misses precisely so a busy counter that
    mistypes now and then, between real handovers, never trips it.
    """
    code = await _code_for(db, str(paid_order["id"]))
    limit = settings.PICKUP_MISS_LIMIT

    # One short of the cap...
    for _ in range(limit - 1):
        assert (await _miss(client, seed["owner_auth"])).status_code == 200

    # ...then a real code, which resets the counter.
    hit = await _miss(client, seed["owner_auth"], code=code)
    assert hit.status_code == 200, hit.text
    assert hit.json()["found"] is True

    # The full budget is available again: without the reset, the first of
    # these would be the cap-th miss and the last would 429.
    for i in range(limit):
        r = await _miss(client, seed["owner_auth"])
        assert r.status_code == 200, (
            f"a successful lookup must clear the run — miss {i + 1} 429'd: {r.text}"
        )


async def test_the_cap_is_scoped_per_outlet(client, seed, paid_order, rival, db):
    """One restaurant's fumbling must never stop another taking pickups.

    A shared or global counter would make this a denial-of-service against
    every other outlet on the deployment.
    """
    for _ in range(settings.PICKUP_MISS_LIMIT + 1):
        await _miss(client, seed["owner_auth"])
    assert (await _miss(client, seed["owner_auth"])).status_code == 429

    # The rival is untouched — and its own real code still resolves.
    r = await _miss(client, rival["auth"])
    assert r.status_code == 200, (
        f"outlet A's misses locked out outlet B: {r.status_code} {r.text}"
    )
    assert r.json()["found"] is False


async def test_verify_pickup_misses_count_toward_the_same_cap(
    client, seed, paid_order, rival, db
):
    """Enumerating order ids through verify-pickup is the other free branch.

    Its 404 resolves no order, so the per-order counter never sees it. This is
    the same hole in a different route, and it shares the cap.
    """
    order_id = str(paid_order["id"])
    code = await _code_for(db, order_id)

    # The rival probes with a real order id + real code — the exact shape of
    # the cross-outlet attack the 404 scoping fix closed.
    for _ in range(settings.PICKUP_MISS_LIMIT):
        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=rival["auth"],
                              json={"order_id": order_id, "pickup_code": code})
        assert r.status_code == 404, r.text

    blocked = await client.post(f"{API}/pos/orders/verify-pickup",
                                headers=rival["auth"],
                                json={"order_id": order_id, "pickup_code": code})
    assert blocked.status_code == 429, (
        f"cross-outlet probing is unmetered: {blocked.status_code} {blocked.text}"
    )

    # Throughout, the real order was never touched, and its own outlet is
    # unaffected by the rival burning through its budget.
    assert await _status_of(db, order_id) == "PAID"
    ok = await client.post(f"{API}/pos/orders/lookup-pickup",
                           headers=seed["owner_auth"], json={"pickup_code": code})
    assert ok.status_code == 200 and ok.json()["found"] is True


async def test_a_wrong_code_on_a_found_order_still_uses_the_3_strike_path(
    client, seed, paid_order, db
):
    """The two limits must not double-count.

    A found order with a wrong code is the per-order lockout's business. It
    must not also drain the outlet's miss budget, or three typos on one order
    would start eating into the counter's ability to serve everyone else.
    """
    order_id = str(paid_order["id"])

    for _ in range(2):
        r = await client.post(f"{API}/pos/orders/verify-pickup",
                              headers=seed["owner_auth"],
                              json={"order_id": order_id, "pickup_code": "234567"})
        assert r.status_code == 200, r.text
        assert r.json()["verified"] is False

    # Checked behaviourally rather than by reading the dict: asserting the key
    # is absent would pass just as well if the key were merely spelled
    # differently. Spending the WHOLE budget afterwards can only succeed if
    # those two attempts really cost the outlet nothing.
    for i in range(settings.PICKUP_MISS_LIMIT):
        r = await _miss(client, seed["owner_auth"])
        assert r.status_code == 200, (
            f"the 3-strike path drained the outlet budget — miss {i + 1} 429'd: {r.text}"
        )

    # And the per-order counter did its job.
    attempts = await db.scalar(
        text("SELECT failed_attempts FROM customer_orders WHERE id = :i"),
        {"i": order_id},
    )
    assert attempts == 2
