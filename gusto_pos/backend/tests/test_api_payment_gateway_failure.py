"""POST /customer/orders when the PAYMENT GATEWAY itself fails.

WHAT WAS WRONG
--------------
`create_order` called `gw.create_order(...)` with nothing around it. Every way
that call can fail raised a bare `RuntimeError` (gateway.py: unconfigured
credentials, a >=400 from Cashfree, a missing payment_session_id), an `httpx`
transport error, or a `ValueError` out of `res.json()` — and FastAPI turns an
unhandled exception into a naked 500 with the body
`{"detail": "Internal Server Error"}`.

The customer app renders that as "Request failed (500)." on the payment page
(api_client.dart:392) — no cause, nothing actionable, and indistinguishable
from a crash in our own code. The gateway being unreachable or misconfigured is
an UPSTREAM/CONFIG condition, not an internal error, and it is also the single
most likely thing to be wrong on a fresh deploy: render.yaml sets
PAYMENT_GATEWAY=cashfree as a literal value while CASHFREE_APP_ID and
CASHFREE_SECRET_KEY are `sync: false`, i.e. dashboard-only secrets that the
blueprint cannot supply.

A second, quieter 500 lived in the request body itself. Cashfree documents
`order_amount` with "minimum: 1", and a points coupon or a 100%-off promotion
whose discount meets the basket total settles the order at ₹0 — an ordinary
customer action that reached the wire and came back a 400, i.e. a 500.

WHAT IS ASSERTED
----------------
  * Never a 500. 503 when WE are unconfigured, 502 when the PROVIDER failed,
    422 when the order cannot be charged as it stands.
  * A structured detail carrying `error` and `message`, because `message` is
    the only shape the app renders as prose (api_client.dart:411
    `_detailMessage`) and `error` is the stable code it can branch on. This is
    the form the other money-path refusals already use (ITEM_SOLD_OUT,
    UNPAID_ORDER_PENDING).
  * The failure is LOGGED with the order id and the provider's response body,
    and never with a credential.
  * NOTHING IS PERSISTED. The order row is flushed and the stock hold taken
    BEFORE the gateway is called, so a failure here must leave no CREATED
    order, no reservation row and no decremented stock. This is the property
    that matters most: an error the customer can retry is only safe if the
    first attempt left nothing behind to collide with the second.
  * The request body matches the fields Cashfree documents, checked on the
    body actually handed to httpx rather than on a helper in isolation.
"""
from __future__ import annotations

import logging
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings

API = "/api/v1"

# A credential that must never turn up in a log line.
SECRET = "TEST_SECRET_cf_do_not_log"


def _body(seed, qty: int = 1) -> dict:
    return {"outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": qty}]}


def _select_cashfree(monkeypatch, *, configured: bool) -> None:
    """Point the factory at Cashfree, with or without credentials."""
    monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
    monkeypatch.setattr(settings, "CASHFREE_APP_ID",
                        "TEST_APP_ID" if configured else None)
    monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY",
                        SECRET if configured else None)


class _FakeResponse:
    """Minimal stand-in for httpx.Response as gateway.create_order uses it."""

    def __init__(self, status_code: int, payload=None, text_body: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text_body

    def json(self):
        if self._payload is None:
            # What a real httpx.Response does with a non-JSON body.
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _patch_post(monkeypatch, responder) -> None:
    """Replace the AsyncClient the GATEWAY constructs, nothing wider.

    Patching `httpx.AsyncClient.post` is the obvious move and it is wrong: the
    in-process test client is an httpx.AsyncClient too, so the patch hijacks
    the test's OWN request and the app is never reached — every assertion then
    reads the fake gateway response back as if it were the API's answer, which
    is how a test like this passes while proving nothing.

    Swapping the class is safe because the test client instance was already
    built from the real one; only the gateway constructs a new client after
    this point. Same technique as test_api_stock_hold_ttl.py.
    """
    from app.modules.carevo_payments import gateway as gw_mod

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return await responder(url, headers=headers, json=json)

    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", _Client)


async def _issue_full_value_coupon(db, customer_id) -> str:
    """One ACTIVE POINTS_DISCOUNT coupon worth the whole ₹100 basket.

    The code is unique per call: `coupons.code` is globally unique and the
    test database is not dropped between runs, so a fixed literal passes once
    and then fails forever with a UniqueViolation.
    """
    code = f"PTS{uuid.uuid4().hex[:12].upper()}"
    await db.execute(text("""
        INSERT INTO coupons (id, code, customer_id, kind, discount_amount,
                             trial_days, status, created_at)
        VALUES (:id, :code, :cid, 'POINTS_DISCOUNT', 100, 0, 'ACTIVE', now())
    """), {"id": str(uuid.uuid4()), "code": code, "cid": customer_id})
    await db.commit()
    return code


def _ok_responder(captured: dict):
    """A working Cashfree, recording the body it was sent."""
    async def _post(url, **kwargs):
        captured.update(kwargs.get("json") or {})
        return _FakeResponse(200, {"payment_session_id": "sess_test",
                                   "cf_order_id": "cf_test",
                                   "order_amount": 100.0,
                                   "order_currency": "INR"})
    return _post


# ===================== 1. our configuration is wrong =========================
class TestUnconfiguredGatewayIsA503:
    async def test_cashfree_selected_but_credentials_missing(
            self, client, seed, monkeypatch):
        """The prod-shaped misconfiguration: selector flipped, secrets absent."""
        _select_cashfree(monkeypatch, configured=False)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 503, r.text
        detail = r.json()["detail"]
        assert isinstance(detail, dict), detail
        assert detail["error"] == "PAYMENT_GATEWAY_UNCONFIGURED"
        assert detail["message"]
        # The customer-facing message must not leak the provider's name or our
        # configuration state — it is shown verbatim in the app.
        assert "CASHFREE_APP_ID" not in detail["message"]
        assert "ashfree" not in detail["message"]
        assert r.headers.get("Retry-After") == "30"

    async def test_the_misconfiguration_is_logged_with_the_order_id(
            self, client, seed, monkeypatch, caplog):
        """Silent is not an option: this one is only ever fixed by an operator
        reading the log, so the log has to say what happened and to which
        order."""
        _select_cashfree(monkeypatch, configured=False)

        with caplog.at_level(logging.WARNING,
                             logger="app.modules.carevo_customer.service"):
            r = await client.post(f"{API}/customer/orders",
                                  headers=seed["customer_auth"],
                                  json=_body(seed))
        assert r.status_code == 503

        logged = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "NOT CONFIGURED" in logged, logged
        assert str(seed["outlet_id"]) in logged, logged


# ======================= 2. the provider failed ==============================
class TestUpstreamFailureIsA502:
    async def test_gateway_rejects_the_order(self, client, seed, monkeypatch):
        """Cashfree answers 401/400 — e.g. wrong or sandbox-vs-prod credentials."""
        _select_cashfree(monkeypatch, configured=True)

        async def _unauthorized(url, **kwargs):
            return _FakeResponse(401, {},
                                 text_body='{"message":"authentication Failed"}')

        _patch_post(monkeypatch, _unauthorized)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_GATEWAY_ERROR"
        assert r.json()["detail"]["message"]

    async def test_gateway_returns_no_payment_session(
            self, client, seed, monkeypatch):
        """A 200 with no payment_session_id — nothing for the SDK to open."""
        _select_cashfree(monkeypatch, configured=True)

        async def _sessionless(url, **kwargs):
            return _FakeResponse(200, {"cf_order_id": "abc", "order_amount": 100})

        _patch_post(monkeypatch, _sessionless)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_GATEWAY_ERROR"

    async def test_a_2xx_carrying_html_is_not_a_crash(
            self, client, seed, monkeypatch):
        """A proxy error page under a 200 makes res.json() raise ValueError."""
        _select_cashfree(monkeypatch, configured=True)

        async def _html(url, **kwargs):
            return _FakeResponse(200, None,
                                 text_body="<html>502 Bad Gateway</html>")

        _patch_post(monkeypatch, _html)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_GATEWAY_ERROR"

    async def test_a_2xx_carrying_a_json_array_is_not_a_crash(
            self, client, seed, monkeypatch):
        """`data.get(...)` on a list would be an AttributeError, i.e. a 500."""
        _select_cashfree(monkeypatch, configured=True)

        async def _array(url, **kwargs):
            return _FakeResponse(200, [], text_body="[]")

        _patch_post(monkeypatch, _array)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text

    async def test_gateway_unreachable(self, client, seed, monkeypatch):
        """Transport failure: DNS, TLS, timeout. Not a RuntimeError at all."""
        _select_cashfree(monkeypatch, configured=True)

        async def _boom(url, **kwargs):
            raise httpx.ConnectError("name resolution failed")

        _patch_post(monkeypatch, _boom)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_GATEWAY_ERROR"

    async def test_timeout_is_also_a_502(self, client, seed, monkeypatch):
        _select_cashfree(monkeypatch, configured=True)

        async def _slow(url, **kwargs):
            raise httpx.ReadTimeout("gateway took too long")

        _patch_post(monkeypatch, _slow)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 502, r.text

    async def test_the_failure_is_logged_with_the_order_id_and_the_body(
            self, client, seed, monkeypatch, caplog):
        """Cashfree's own error JSON names the offending field. Losing it means
        the next person debugging this has nothing but "502"."""
        _select_cashfree(monkeypatch, configured=True)

        async def _rejected(url, **kwargs):
            return _FakeResponse(
                400, {},
                text_body='{"code":"order_amount_invalid","message":"bad"}')

        _patch_post(monkeypatch, _rejected)

        with caplog.at_level(logging.WARNING,
                             logger="app.modules.carevo_customer.service"):
            r = await client.post(f"{API}/customer/orders",
                                  headers=seed["customer_auth"],
                                  json=_body(seed))
        assert r.status_code == 502

        logged = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "order_amount_invalid" in logged, logged
        assert str(seed["outlet_id"]) in logged, logged

    async def test_the_log_never_contains_the_secret_key(
            self, client, seed, monkeypatch, caplog):
        """The whole point of logging the response body is that it is THEIRS.
        Nothing on this path may print what we authenticate with."""
        _select_cashfree(monkeypatch, configured=True)

        async def _rejected(url, **kwargs):
            return _FakeResponse(401, {}, text_body='{"message":"auth failed"}')

        _patch_post(monkeypatch, _rejected)

        with caplog.at_level(logging.DEBUG):
            r = await client.post(f"{API}/customer/orders",
                                  headers=seed["customer_auth"],
                                  json=_body(seed))
        assert r.status_code == 502

        whole_log = "\n".join(
            [rec.getMessage() for rec in caplog.records]
            + [str(rec.exc_info) for rec in caplog.records])
        assert SECRET not in whole_log
        assert "TEST_APP_ID" not in whole_log


# ============ 3. the order cannot be charged as it stands ====================
class TestUnchargeableOrderIsA422:
    """Cashfree documents order_amount with "minimum: 1"."""

    async def test_a_zero_rupee_order_is_a_422_not_a_500(
            self, client, seed, db, monkeypatch):
        """A points coupon worth the whole basket settles the order at ₹0.
        `_consume_points_coupon` caps the discount AT the gross, so this is
        reachable with one ordinary coupon and no special state."""
        _select_cashfree(monkeypatch, configured=True)

        captured: dict = {}
        _patch_post(monkeypatch, _ok_responder(captured))

        code = await _issue_full_value_coupon(db, seed["customer_id"])
        payload = dict(_body(seed, qty=1), coupon_code=code)
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=payload)

        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "AMOUNT_BELOW_GATEWAY_MINIMUM"
        assert detail["message"]
        assert not captured, \
            "an unchargeable amount was sent to the gateway anyway"

    async def test_the_coupon_is_not_burned_by_the_refusal(
            self, client, seed, db, monkeypatch):
        """The refusal rolls the whole transaction back, so the coupon the
        customer paid points for is still theirs."""
        _select_cashfree(monkeypatch, configured=True)
        _patch_post(monkeypatch, _ok_responder({}))

        code = await _issue_full_value_coupon(db, seed["customer_id"])

        r = await client.post(
            f"{API}/customer/orders", headers=seed["customer_auth"],
            json=dict(_body(seed, qty=1), coupon_code=code))
        assert r.status_code == 422, r.text

        status = await db.scalar(
            text("SELECT status FROM coupons WHERE code = :c"), {"c": code})
        assert status == "ACTIVE", "a refused order spent the customer's coupon"


# ============ 3b. the schema the code needs is not there =====================
class TestSchemaDriftIsA503:
    """Migrations here are applied BY HAND — render.yaml runs `pip install`
    then `uvicorn`, with no migration step — so code can reach production
    ahead of its tables. `create_order`'s first statement writes to
    `stock_reservations` (migration 033) and the insert after it names the
    nine columns migration 032 adds to `customer_orders`.

    This does not repair the drift and is not meant to: it stays 5xx and the
    traceback is still logged. What it removes is "Request failed (500)." as
    the customer's entire explanation.
    """

    @staticmethod
    def _undefined_table() -> ProgrammingError:
        """What asyncpg + SQLAlchemy raise for a missing table."""
        return ProgrammingError(
            'UPDATE stock_reservations sr SET state = $1', {},
            Exception('relation "stock_reservations" does not exist'))

    async def test_a_missing_table_is_a_503_not_a_500(
            self, client, seed, monkeypatch):
        from app.modules.carevo_customer.stock import StockService

        async def _undefined(*a, **k):
            raise TestSchemaDriftIsA503._undefined_table()

        monkeypatch.setattr(StockService, "sweep_expired", _undefined)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))

        assert r.status_code == 503, r.text
        detail = r.json()["detail"]
        assert detail["error"] == "SERVICE_SCHEMA_OUT_OF_DATE"
        assert detail["message"]
        assert r.headers.get("Retry-After") == "60"

    async def test_the_drift_is_logged_loudly_with_a_traceback(
            self, client, seed, monkeypatch, caplog):
        """Masking a missing migration behind a friendly message would delay
        the only action that fixes it. The log must name the condition."""
        from app.modules.carevo_customer.stock import StockService

        async def _undefined(*a, **k):
            raise TestSchemaDriftIsA503._undefined_table()

        monkeypatch.setattr(StockService, "sweep_expired", _undefined)

        with caplog.at_level(logging.ERROR,
                             logger="app.modules.carevo_customer.controller"):
            r = await client.post(f"{API}/customer/orders",
                                  headers=seed["customer_auth"],
                                  json=_body(seed))
        assert r.status_code == 503

        records = [rec for rec in caplog.records
                   if "live schema" in rec.getMessage()]
        assert records, [rec.getMessage() for rec in caplog.records]
        assert "032/033" in records[0].getMessage()
        assert str(seed["outlet_id"]) in records[0].getMessage()
        assert records[0].exc_info is not None, "logged without the traceback"

    async def test_a_real_constraint_violation_is_not_swallowed(
            self, client, seed, monkeypatch):
        """The guard is ProgrammingError only. An IntegrityError is a genuine
        bug in our logic and must not be dressed up as a maintenance window."""
        from sqlalchemy.exc import IntegrityError
        from app.modules.carevo_customer.stock import StockService

        async def _violation(*a, **k):
            raise IntegrityError("INSERT ...", {}, Exception("duplicate key"))

        monkeypatch.setattr(StockService, "sweep_expired", _violation)

        with pytest.raises(IntegrityError):
            await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))


# ================== 4. nothing is left behind ================================
class TestNothingIsPersistedOnGatewayFailure:
    async def test_no_order_no_hold_no_decrement(
            self, client, seed, db, monkeypatch):
        """The order and the stock hold both precede the gateway call."""
        # Track stock so a hold would be visible if one survived.
        await db.execute(
            text("UPDATE menu_items SET stock_remaining = 5 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()

        _select_cashfree(monkeypatch, configured=False)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json=_body(seed, qty=2))
        assert r.status_code == 503, r.text

        orders = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE customer_id = :c"),
            {"c": seed["customer_id"]})
        assert orders == 0, "a failed checkout left an orphan order behind"

        holds = await db.scalar(text("""
            SELECT count(*) FROM stock_reservations sr
              JOIN customer_orders co ON co.id = sr.order_id
             WHERE co.customer_id = :c"""), {"c": seed["customer_id"]})
        assert holds == 0, "a failed checkout left a stock hold behind"

        remaining = await db.scalar(text(
            "SELECT stock_remaining FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        assert remaining == 5, "stock was consumed by an order that never existed"

    async def test_an_upstream_502_leaves_nothing_behind_either(
            self, client, seed, db, monkeypatch):
        """Same property on the other branch: the 502 is only safely
        retryable if the first attempt wrote nothing."""
        await db.execute(
            text("UPDATE menu_items SET stock_remaining = 5 WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()

        _select_cashfree(monkeypatch, configured=True)

        async def _boom(url, **kwargs):
            raise httpx.ConnectError("name resolution failed")

        _patch_post(monkeypatch, _boom)

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json=_body(seed, qty=2))
        assert r.status_code == 502, r.text

        orders = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE customer_id = :c"),
            {"c": seed["customer_id"]})
        assert orders == 0
        remaining = await db.scalar(text(
            "SELECT stock_remaining FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        assert remaining == 5

    async def test_retry_after_a_failure_succeeds(
            self, client, seed, monkeypatch):
        """The refusal is genuinely retryable: a working gateway on the next
        attempt produces a normal order, with no residue from the first."""
        _select_cashfree(monkeypatch, configured=False)
        first = await client.post(f"{API}/customer/orders",
                                  headers=seed["customer_auth"], json=_body(seed))
        assert first.status_code == 503

        # Back to the stub (what the suite runs on) and try again.
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        second = await client.post(f"{API}/customer/orders",
                                   headers=seed["customer_auth"], json=_body(seed))
        assert second.status_code == 200, second.text
        assert second.json()["payment"]["gateway"]


# ============ 5. the body we send matches Cashfree's contract ================
class TestTheRequestBodyMatchesTheDocumentedContract:
    """Asserted on the body actually handed to httpx, not on the helpers in
    isolation — a correct helper that nothing calls fixes nothing."""

    async def test_customer_id_is_alphanumeric_only(
            self, client, seed, monkeypatch):
        """We pass `customers.id`. A UUID's canonical spelling carries four
        hyphens, and the Create Order reference says of this field "Use
        alphanumeric values only" (minLength 3, maxLength 50)."""
        _select_cashfree(monkeypatch, configured=True)
        captured: dict = {}
        _patch_post(monkeypatch, _ok_responder(captured))

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))
        assert r.status_code == 200, r.text

        cid = captured["customer_details"]["customer_id"]
        assert cid.isalnum() and cid.isascii(), cid
        assert 3 <= len(cid) <= 50, cid
        # Still this customer, just without the punctuation.
        assert cid == str(seed["customer_id"]).replace("-", "")

    async def test_order_id_keeps_its_hyphens(self, client, seed, monkeypatch):
        """order_id is the OTHER rule — "alphanumeric characters, underscores
        (_), and hyphens (-)" — and the webhook finds our order by it, so
        stripping anything here would break correlation."""
        _select_cashfree(monkeypatch, configured=True)
        captured: dict = {}
        _patch_post(monkeypatch, _ok_responder(captured))

        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json=_body(seed))
        assert r.status_code == 200, r.text

        assert captured["order_id"] == r.json()["id"]
        assert 3 <= len(captured["order_id"]) <= 45

    async def test_an_amount_below_one_rupee_never_reaches_the_wire(
            self, monkeypatch):
        from app.modules.carevo_payments.gateway import (
            CashfreeGateway, GatewayRequestError)

        monkeypatch.setattr(settings, "CASHFREE_APP_ID", "TEST_APP_ID")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", SECRET)

        async def _never(url, **kwargs):
            raise AssertionError("the gateway was called with an invalid amount")

        _patch_post(monkeypatch, _never)

        with pytest.raises(GatewayRequestError) as exc:
            await CashfreeGateway().create_order(0.0, receipt=str(uuid.uuid4()))
        assert exc.value.code == "AMOUNT_BELOW_GATEWAY_MINIMUM"
        assert exc.value.customer_message

    @pytest.mark.parametrize("stored,expected", [
        # Firebase phone sign-in stores E.164; the '+' is what lifts Cashfree's
        # 10-character limit, so it must survive.
        ("+919876543210", "+919876543210"),
        # A bare Indian number is the other documented spelling.
        ("9876543210", "9876543210"),
        # Country code without the '+' would blow the 10-char limit.
        ("919876543210", "+919876543210"),
        # Legacy rows from the pre-Firebase stub flow.
        ("+91 98765 43210", "+919876543210"),
        ("98765-43210", "9876543210"),
        # Google-only customers have no phone on file at all.
        (None, "9999999999"),
        ("", "9999999999"),
        ("123", "9999999999"),
    ])
    def test_phone_is_reduced_to_a_documented_spelling(self, stored, expected):
        from app.modules.carevo_payments.gateway import CashfreeGateway
        assert CashfreeGateway._customer_phone(stored) == expected

    def test_a_customer_id_with_no_usable_characters_falls_back(self):
        from app.modules.carevo_payments.gateway import CashfreeGateway
        assert CashfreeGateway._customer_id(None) == "guest"
        assert CashfreeGateway._customer_id("--") == "guest"
        # And a long one is cut to the documented maximum, not sent over it.
        assert len(CashfreeGateway._customer_id("a" * 80)) == 50


# ===================== 6. the stub path is unchanged =========================
class TestStubPathIsUnchanged:
    async def test_stub_gateway_still_creates_orders(self, client, seed):
        """Guard against the fix accidentally catching the happy path."""
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json=_body(seed, qty=2))
        assert r.status_code == 200, r.text
        assert r.json()["final_amount"] == 200.0

    async def test_the_stub_still_takes_a_zero_rupee_order(
            self, client, seed, db):
        """The ₹1 floor is CASHFREE's, enforced in CashfreeGateway. The stub
        has no such constraint and a fully-discounted order must still work on
        a stub deploy."""
        code = await _issue_full_value_coupon(db, seed["customer_id"])

        r = await client.post(
            f"{API}/customer/orders", headers=seed["customer_auth"],
            json=dict(_body(seed, qty=1), coupon_code=code))
        assert r.status_code == 200, r.text
        assert r.json()["final_amount"] == 0.0


# ---------------------------------------------------------------------------
# YOUPI edge key
#
# YOUPI leaves POST /api/v1/payments unauthenticated (auth-guard.js returns
# null for it), so a Cloudflare custom rule blocking the path unless
# X-Gusto-Edge-Key matches is the only thing in front of it. Two properties
# matter and both are pinned here:
#
#   1. when the key IS configured, every create_order carries the header;
#   2. when it is NOT, the order fails with the structured config error rather
#      than going out bare -- a bare request is blocked at the edge and comes
#      back as an opaque 403, which is a worse failure than refusing up front.
# ---------------------------------------------------------------------------
EDGE_KEY = "TEST_EDGE_KEY_do_not_log"


def _select_youpi(monkeypatch, *, edge_key) -> None:
    """Point the factory at YOUPI. `edge_key=None` simulates an unset env var."""
    monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "youpi")
    monkeypatch.setattr(settings, "YOUPI_BASE_URL", "https://youpi.example.test")
    monkeypatch.setattr(settings, "YOUPI_WEBHOOK_SECRET", "TEST_WEBHOOK_SECRET")
    monkeypatch.setattr(settings, "YOUPI_MERCHANT_ID", None)
    monkeypatch.setattr(settings, "YOUPI_EDGE_KEY", edge_key)


@pytest.mark.asyncio
async def test_youpi_create_order_sends_the_edge_key_header(monkeypatch):
    from app.modules.carevo_payments.gateway import get_gateway

    _select_youpi(monkeypatch, edge_key=EDGE_KEY)
    seen = {}

    async def responder(url, headers=None, json=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _FakeResponse(201, {
            "paymentId": "11111111-2222-3333-4444-555555555555",
            "amountPaise": "100", "currency": "INR",
            "checkoutUrl": "https://youpi.example.test/checkout/x",
        })

    _patch_post(monkeypatch, responder)

    gw = get_gateway()
    assert gw.name == "youpi"
    order = await gw.create_order(1.00, receipt="ORDER-EDGE-1")

    assert seen["url"].endswith("/api/v1/payments")
    assert seen["headers"].get("X-Gusto-Edge-Key") == EDGE_KEY, (
        "create_order reached YOUPI without the edge key; the WAF rule would "
        "block this and the failure would surface as an opaque 403"
    )
    assert order.gateway == "youpi"


@pytest.mark.asyncio
async def test_youpi_refuses_to_create_an_order_without_the_edge_key(monkeypatch):
    from app.modules.carevo_payments.gateway import GatewayConfigError, get_gateway

    _select_youpi(monkeypatch, edge_key=None)

    called = {"n": 0}

    async def responder(url, headers=None, json=None):   # pragma: no cover
        called["n"] += 1
        return _FakeResponse(201, {"paymentId": "x"})

    _patch_post(monkeypatch, responder)

    gw = get_gateway()
    assert gw.configured is False

    with pytest.raises(GatewayConfigError) as exc:
        await gw.create_order(1.00, receipt="ORDER-EDGE-2")

    assert "YOUPI_EDGE_KEY" in str(exc.value)
    assert called["n"] == 0, "a request went out despite the missing edge key"
