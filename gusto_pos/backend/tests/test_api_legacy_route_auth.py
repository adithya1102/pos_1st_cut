"""The legacy-route auth split, pinned in both directions.

Two lists, and BOTH are load-bearing.

GUARDED is the set closed in this pass: routes that were reachable with no
credentials at all and that the caller audit found nothing in this repository
calling. Worst of them was `GET /customers/phone/{phone_number}` — a PII lookup
keyed on exactly the identifier a stranger is most likely to have — alongside
the full customer table, outlet deletion, and menu price mutation.

STILL_OPEN is the set deliberately NOT closed: GustoPOS and GustoWaiter call
every one of these, and neither app sends an Authorization header (there is no
login flow in either — `PinLoginResponse` exists as a model and is referenced
nowhere). Guarding them would take the tills and waiter tablets offline.

Asserting the second list is the point. A well-meaning "let's finish the job"
change that adds the guard router-wide would pass a test that only checked the
first list, and would be discovered by a restaurant instead. This file fails
first.

Every id here is a FRESH RANDOM UUID, never a seeded one, so the destructive
verbs resolve to 404 and the suite cannot delete its own fixtures while
proving an auth boundary.
"""
import uuid

import pytest
from fastapi.exceptions import ResponseValidationError

from tests.conftest import API


def rid() -> str:
    return str(uuid.uuid4())


# --- closed in this pass: 401 without a staff token ------------------------
GUARDED = [
    # customers/* — router-wide. The PII exposure.
    ("GET",    f"{API}/customers/"),
    ("GET",    f"{API}/customers/{rid()}"),
    ("GET",    f"{API}/customers/phone/+919999000011"),
    ("POST",   f"{API}/customers/"),
    ("PUT",    f"{API}/customers/{rid()}"),
    ("DELETE", f"{API}/customers/{rid()}"),
    # outlets/* — router-wide. Includes unauthenticated outlet deletion.
    ("GET",    f"{API}/outlets/"),
    ("GET",    f"{API}/outlets/{rid()}"),
    ("POST",   f"{API}/outlets/"),
    ("PUT",    f"{API}/outlets/{rid()}"),
    ("DELETE", f"{API}/outlets/{rid()}"),
    # menus/* — the 15 with no caller. Leaves the 6 GustoPOS/Waiter use.
    ("GET",    f"{API}/menus/by-zone/{rid()}/normal"),
    ("PATCH",  f"{API}/menus/price-rule"),
    ("POST",   f"{API}/menus/"),
    ("GET",    f"{API}/menus/outlet/{rid()}"),
    ("PUT",    f"{API}/menus/{rid()}"),
    ("DELETE", f"{API}/menus/{rid()}"),
    ("GET",    f"{API}/menus/categories/{rid()}"),
    ("DELETE", f"{API}/menus/categories/{rid()}"),
    ("GET",    f"{API}/menus/items/{rid()}"),
    ("GET",    f"{API}/menus/items/category/{rid()}"),
    ("DELETE", f"{API}/menus/items/{rid()}"),
    ("POST",   f"{API}/menus/modifiers/{rid()}"),
    ("GET",    f"{API}/menus/modifiers/{rid()}"),
    ("GET",    f"{API}/menus/modifiers/item/{rid()}"),
    ("DELETE", f"{API}/menus/modifiers/{rid()}"),
    # categories/* — the 3 with no caller. PUT/DELETE stay open (GustoPOS).
    ("GET",    f"{API}/categories/"),
    ("GET",    f"{API}/categories/{rid()}"),
    ("POST",   f"{API}/categories/"),
    # orders/* — the 4 with no caller, out of 20.
    ("GET",    f"{API}/orders/history/{rid()}"),
    ("GET",    f"{API}/orders/summary/{rid()}"),
    ("DELETE", f"{API}/orders/{rid()}"),
    ("PUT",    f"{API}/orders/{rid()}/items"),

    # ---- closed in the SECOND pass (security audit follow-up) --------------
    # Eight whole routers, guarded router-wide. The caller audit for this pass
    # enumerated every `{Base}/...` path in both MAUI ApiService files and
    # grepped admin_app, owner_app, customer_app, gusto_pos/customer_app,
    # dashboard_app and mcp_server. Nothing calls any of these.
    #
    # users/* was the worst of the eight and the reason the pass happened:
    # POST /users/ accepted arbitrary role_ids with no credential, so anyone
    # could mint themselves a privileged account and then log into it.
    ("GET",    f"{API}/users/"),
    ("GET",    f"{API}/users/{rid()}"),
    ("POST",   f"{API}/users/"),
    ("PUT",    f"{API}/users/{rid()}"),
    ("DELETE", f"{API}/users/{rid()}"),
    # roles/* — the JSONB permission sets, previously writable anonymously.
    ("GET",    f"{API}/roles/"),
    ("GET",    f"{API}/roles/{rid()}"),
    ("POST",   f"{API}/roles/"),
    ("PUT",    f"{API}/roles/{rid()}"),
    ("DELETE", f"{API}/roles/{rid()}"),
    # organizations/* — top of the tenancy hierarchy, DELETE included.
    ("GET",    f"{API}/organizations/"),
    ("GET",    f"{API}/organizations/{rid()}"),
    ("POST",   f"{API}/organizations/"),
    ("PUT",    f"{API}/organizations/{rid()}"),
    ("DELETE", f"{API}/organizations/{rid()}"),
]

# --- never mounted, therefore never reachable ------------------------------
# A correction to the security audit that prompted this pass. The audit scanned
# CONTROLLER FILES and counted every @router decorator it found; it did not
# check app/main.py for which routers are actually include_router'd. These five
# are not, so they answered 404 to everyone and always have — they were never
# an exposure at all.
#
# Their controllers now carry the router-level guard anyway, so that mounting
# one later cannot quietly reintroduce an open surface. That is defence in
# depth, not a fix, and this list says so rather than letting the GUARDED list
# take credit for closing something that was never open.
NOT_MOUNTED = [
    ("GET",    f"{API}/order-items/"),
    ("POST",   f"{API}/order-items/"),
    ("GET",    f"{API}/inventory/"),
    ("POST",   f"{API}/inventory/"),
    ("GET",    f"{API}/products/"),
    ("POST",   f"{API}/products/"),
    ("GET",    f"{API}/sync-logs/"),
    ("POST",   f"{API}/sync-logs/"),
    ("GET",    f"{API}/audit-logs/"),
    ("POST",   f"{API}/audit-logs/"),
]

# --- deliberately still open: MUST NOT 401 ---------------------------------
# Every entry is a confirmed GustoPOS or GustoWaiter call site.
STILL_OPEN = [
    ("PUT",    f"{API}/categories/{rid()}"),                    # POS ApiService:309,933
    ("DELETE", f"{API}/categories/{rid()}"),                    # POS :320,948
    ("POST",   f"{API}/menus/categories/"),                     # POS :296,916
    ("GET",    f"{API}/menus/categories/menu/{rid()}"),         # POS :284,901
    ("POST",   f"{API}/menus/items/"),                          # POS :82,544
    ("PUT",    f"{API}/menus/items/{rid()}"),                   # POS :64,331,520,963
    ("GET",    f"{API}/menus/zone/{rid()}/normal"),             # POS :30,475 / Waiter :50,439
    ("GET",    f"{API}/menus/{rid()}"),                         # POS :21,461 / Waiter :74,471
    ("GET",    f"{API}/orders/"),                               # POS :104,578 / Waiter :192,618
    ("POST",   f"{API}/orders/"),                               # POS :53,188,504,770
    ("POST",   f"{API}/orders/bill/combined"),                  # POS :635
    ("POST",   f"{API}/orders/bill/{rid()}"),                   # POS :130,162,661,723
    ("GET",    f"{API}/orders/pending-approval"),               # Waiter :424
    ("GET",    f"{API}/orders/sales-summary/"),                 # POS SalesAndProfitPage:34
    ("POST",   f"{API}/orders/settle/{rid()}"),                 # POS :140,691
    ("GET",    f"{API}/orders/table/{rid()}"),                  # POS :121,606 / Waiter :276,696,840
    ("GET",    f"{API}/orders/table/{rid()}/active-items"),     # Waiter :750
    ("GET",    f"{API}/orders/table/{rid()}/combined"),         # POS :620
    ("GET",    f"{API}/orders/{rid()}"),                        # Waiter :114,523,712
    ("PUT",    f"{API}/orders/{rid()}"),                        # POS :111,589
    ("POST",   f"{API}/orders/{rid()}/approve"),                # Waiter :393
    ("POST",   f"{API}/orders/{rid()}/cancel"),                 # Waiter :409
    ("POST",   f"{API}/orders/{rid()}/confirm"),                # Waiter :86
    ("PATCH",  f"{API}/orders/{rid()}/items/{rid()}/serve"),    # Waiter :765

    # ---- ADDED in the second pass, and this addition is a FINDING ----------
    # These were on the audit's "guard everything" list. They are NOT guarded,
    # because enumerating every `{Base}/...` literal in the two MAUI
    # ApiService files proved the tills and tablets call them — which the
    # first pass's list had missed. Guarding them is correct eventually and
    # blocked on exactly one thing: both apps already run a PIN login and
    # already store the token (SecureStorage.SetAsync("auth_token")), but
    # never attach it to a request. There is no Authorization header anywhere
    # in either codebase.
    #
    # The worst entry here by a distance is PUT /staff/{id}/pin — resetting
    # any staff member's PIN with no credential, which then yields a token via
    # /auth/pin-login. It stays open ONLY because GustoPOS calls it.
    ("GET",    f"{API}/analytics/free-tables"),                 # POS
    ("GET",    f"{API}/analytics/total-tables"),                # POS
    ("GET",    f"{API}/analytics/top-dish"),                    # POS
    ("GET",    f"{API}/analytics/todays-revenue"),              # POS
    ("GET",    f"{API}/config/{rid()}"),                        # POS config/{id}
    ("GET",    f"{API}/payments/"),                             # POS payments/
    ("GET",    f"{API}/staff/"),                                # POS staff/
    ("POST",   f"{API}/staff/"),                                # POS staff/
    ("PUT",    f"{API}/staff/{rid()}"),                         # POS staff/{id}
    ("DELETE", f"{API}/staff/{rid()}"),                         # POS staff/{id}
    ("PUT",    f"{API}/staff/{rid()}/pin"),                     # POS staff/{id}/pin
    ("POST",   f"{API}/sessions/waiter/action"),                # Waiter
    ("POST",   f"{API}/tables/open"),                           # POS tables/open
    ("POST",   f"{API}/tables/close/{rid()}"),                  # POS tables/close/{id}
    # Customer browser (gusto_pos/customer_app), no token by design.
    ("GET",    f"{API}/menus/zone/{rid()}/normal"),             # also POS/Waiter
    ("GET",    f"{API}/tables/resolve"),
    ("POST",   f"{API}/sessions/send-otp"),
    ("POST",   f"{API}/sessions/verify-otp"),
]

# --- open, but their handler touches a table the test DB does not create ----
# tables/* and sessions/* read `table_sessions`, `customer_sessions` and
# `waiter_notifications` — legacy tables the CareVo test fixture never builds,
# because no CareVo test needs them. Hitting these anonymously therefore raises
# a ProgrammingError from asyncpg instead of returning a status code.
#
# That is still a usable auth assertion, and a strict one: a router-level guard
# rejects BEFORE the handler runs and before any query is issued, so reaching
# the database at all proves the request was not gated. The test below accepts
# either "answered something that is not 401" or "got far enough to fail on a
# missing table", and rejects a clean 401.
STILL_OPEN_DB_BACKED = [
    ("GET", f"{API}/tables/all"),                              # POS tables/all
    ("GET", f"{API}/tables/validate/{rid()}"),                 # customer browser
    ("GET", f"{API}/sessions/status/{rid()}"),                 # customer browser
    ("GET", f"{API}/sessions/waiter/notifications/{rid()}"),   # Waiter
]


async def call(client, method, path, headers=None):
    return await client.request(method, path, headers=headers or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", GUARDED, ids=[f"{m} {p}" for m, p in GUARDED])
async def test_guarded_route_rejects_anonymous(client, method, path):
    r = await call(client, method, path)
    assert r.status_code == 401, (
        f"{method} {path} answered {r.status_code} with no credentials — "
        f"this route is supposed to be closed"
    )


# `GET /customers/` cannot complete even WITH a valid token, and could not
# before this change either: CustomerResponse declares `name: str` and
# `phone_number: str`, while the model has both as `str | None` — nullable
# since Google sign-in landed (migration 008) and a customer may now have no
# phone at all. Serialising the whole table therefore raises
# ResponseValidationError on the first null.
#
# A PRE-EXISTING BUG, surfaced by this test rather than caused by it, and left
# unfixed because changing a response schema is a separate decision from adding
# a guard. Marked strict, so whoever fixes the schema gets an XPASS telling
# them to delete this exemption.
#
# The security half is unaffected: the anonymous-401 case below still covers
# this route, which is the part that mattered.
STAFF_CALLABLE = [
    pytest.param(
        m, p,
        marks=pytest.mark.xfail(
            raises=ResponseValidationError,
            strict=True,
            reason="pre-existing: CustomerResponse requires name/phone_number, "
                   "model allows null (migration 008)",
        ),
    ) if (m, p) == ("GET", f"{API}/customers/") else pytest.param(m, p)
    for m, p in GUARDED
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", STAFF_CALLABLE, ids=[f"{m} {p}" for m, p in GUARDED])
async def test_guarded_route_accepts_staff(client, seed, method, path):
    """A staff token gets PAST the guard.

    Asserted as "not 401" rather than "200": the ids are random, so the
    handlers correctly answer 404, and the write verbs are sent with no body
    so they stop at 422 validation. Either proves the request was authorised —
    which is the only thing this test is about. Pinning a success code would
    be pinning unrelated handler behaviour.
    """
    r = await call(client, method, path, seed["owner_auth"])
    assert r.status_code != 401, (
        f"{method} {path} rejected a valid staff token — the guard is wrong, "
        f"not just present"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", STILL_OPEN, ids=[f"{m} {p}" for m, p in STILL_OPEN])
async def test_tier2_route_still_open(client, method, path):
    """REGRESSION GUARD, and the more important half of this file.

    These are the routes GustoPOS and GustoWaiter call without credentials. If
    one starts answering 401, a till or a waiter tablet stops working, and this
    assertion is the only thing standing between that change and a restaurant
    finding out. Closing them is correct EVENTUALLY — but only once the desktop
    clients send a token, at which point this list shrinks deliberately.
    """
    r = await call(client, method, path)
    assert r.status_code != 401, (
        f"{method} {path} now returns 401, but GustoPOS/GustoWaiter call it "
        f"and send no Authorization header — this breaks the restaurant floor"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", NOT_MOUNTED,
                         ids=[f"{m} {p}" for m, p in NOT_MOUNTED])
async def test_unmounted_router_is_unreachable(client, method, path):
    """404, because app/main.py never include_router's these.

    Pinned so the correction stays true: if someone mounts one of these
    modules later, this test fails and points them at the fact that it now
    needs a deliberate auth decision rather than inheriting one by accident.
    (The guard is already on the router, so mounting is safe — but the change
    should still be conscious.)
    """
    r = await call(client, method, path)
    assert r.status_code == 404, (
        f"{method} {path} answered {r.status_code} — this router is supposed "
        f"to be unmounted. If it was just mounted, confirm its guard is right "
        f"and move it from NOT_MOUNTED into GUARDED."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", STILL_OPEN_DB_BACKED,
                         ids=[f"{m} {p}" for m, p in STILL_OPEN_DB_BACKED])
async def test_db_backed_route_still_open(client, method, path):
    """Same regression guard as above, for handlers that hit absent tables.

    Reaching the query layer is the proof of no-auth-gate; a guard would have
    returned 401 without ever opening a connection.
    """
    from sqlalchemy.exc import SQLAlchemyError

    try:
        r = await call(client, method, path)
    except SQLAlchemyError:
        return  # got into the handler and past any guard — that is the assertion
    assert r.status_code != 401, (
        f"{method} {path} now returns 401, but GustoPOS/GustoWaiter or the "
        f"customer browser call it with no Authorization header"
    )
