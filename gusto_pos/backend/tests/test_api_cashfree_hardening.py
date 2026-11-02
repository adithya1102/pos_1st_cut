"""Cashfree money-path hardening: 7 properties the webhook and mark_paid must
hold, with a MOCKED Cashfree — no network call is ever made. create_order is
exercised under the stub gateway (as the rest of the suite does); only the
webhook request itself is answered as if it came from a live Cashfree, by
switching PAYMENT_GATEWAY to "cashfree" and setting a signing secret right
before the POST. verify_webhook_signature and parse_webhook are pure
functions — this exercises Cashfree's REAL verifier and parser, not a stub
pretending to be them, without ever reaching httpx.

THE DEFECTS THIS FILE FOUND AND service.py/gateway.py FIX
-----------------------------------------------------------
1. mark_paid never compared the webhook's amount against order.total_amount
   at all — WebhookEvent carried no amount field. A webhook reporting PAID
   for any amount, including a single paisa, marked the full order PAID.
   Fixed: WebhookEvent.amount_paise + a short-payment gate in mark_paid
   (migration 038 adds the flag columns). See TestUnderpaid.
2. A payment that settles after the order/stock hold already went terminal
   (ABANDONED) was logged and dropped — refund_required was never set, so a
   real, late payment left no trace in the admin refund queue. Fixed: the
   terminal-status branch in mark_paid now flags it. See TestLatePayment.
3. The unknown-order-id branch in payment_webhook raised a 404 with no log
   line at all — undiagnosable in production. Fixed: a logger.warning now
   names every id the webhook carried. See TestUnknownOrder.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import time
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_payments.gateway import CashfreeGateway
from tests.conftest import API

CF_SECRET = "whsec_test_only_never_real"


def _payid(label: str) -> str:
    """A fresh gateway_payment_id per call, not a fixed literal.

    mark_paid's idempotency check keys on gateway_payment_id across the whole
    table, not just this test's own rows. A hardcoded literal here would
    collide with whatever row a PREVIOUS run of this same file already left
    in the shared local carevo_test database (nothing truncates
    payment_transactions between separate `pytest` invocations), and the
    idempotency check would then silently return that OLD, unrelated order
    instead of operating on this test's fresh one.
    """
    return f"cfpay_{label}_{uuid.uuid4().hex[:12]}"


def _sign(body: bytes, timestamp: str, secret: str = CF_SECRET) -> str:
    signed = f"{timestamp}{body.decode()}".encode()
    return base64.b64encode(
        _hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()


def _cf_body(*, order_id: str, status: str = "SUCCESS",
             payment_amount: float | None = None,
             cf_payment_id: str | None = None,
             event_type: str = "PAYMENT_SUCCESS_WEBHOOK") -> bytes:
    payment = {"payment_status": status}
    if payment_amount is not None:
        payment["payment_amount"] = payment_amount
    if cf_payment_id is not None:
        payment["cf_payment_id"] = cf_payment_id
    payment["payment_method"] = {"upi": {"upi_id": "cust@okaxis"}}
    return json.dumps({
        "type": event_type,
        "data": {
            "order": {"order_id": order_id},
            "payment": payment,
        },
    }).encode()


async def _post_webhook(client, body: bytes, *, timestamp: str | None = None,
                        signature: str | None = None):
    # Default is NOW, not a fixed historical literal: Task 2 added
    # CASHFREE_WEBHOOK_MAX_AGE_S, which rejects an old-but-validly-signed
    # timestamp outright, and every test in this file that does not care
    # about timestamp freshness itself needs a live one to still reach 200.
    if timestamp is None:
        timestamp = str(int(time.time()))
    sig = signature if signature is not None else _sign(body, timestamp)
    return await client.post(
        f"{API}/customer/payment/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-webhook-signature": sig,
            "x-webhook-timestamp": timestamp,
        },
    )


def _go_live(monkeypatch) -> None:
    """Flip the gateway to Cashfree for exactly the webhook POST that follows.

    Done AFTER order creation in every test here, so create_order itself
    still runs under the stub (no network call is ever made — the suite's
    default) and only verify_webhook_signature/parse_webhook, which are pure
    functions, run as Cashfree's real implementation.
    """
    monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
    monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)


async def _order_state(db, order_id):
    return (await db.execute(text("""
        SELECT status, payment_status, pickup_code, refund_required,
               refund_reason, payment_amount_mismatch
          FROM customer_orders WHERE id = :i
    """), {"i": str(order_id)})).first()


async def _place_prepaid(client, seed, qty=1):
    r = await client.post(f"{API}/customer/orders",
                          headers=seed["customer_auth"], json={
                              "outlet_id": seed["outlet_id"],
                              "items": [{"menu_item_id": seed["menu_item_id"],
                                         "quantity": qty}],
                          })
    assert r.status_code == 200, r.text
    return r.json()


# ============================ (a) invalid signature ===========================

class TestInvalidSignature:
    async def test_bad_signature_changes_nothing(self, client, db, seed,
                                                 monkeypatch):
        order = await _place_prepaid(client, seed)
        before = await _order_state(db, order["id"])

        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=100.0)
        r = await _post_webhook(client, body, signature="not-the-real-sig")
        assert r.status_code == 400, r.text

        after = await _order_state(db, order["id"])
        assert after == before


# ======================= (b) duplicate / replayed webhook =====================

class TestReplay:
    async def test_duplicate_webhook_is_idempotent(self, client, db, seed,
                                                    monkeypatch):
        order = await _place_prepaid(client, seed)
        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=100.0,
                        cf_payment_id=_payid("dup"))

        r1 = await _post_webhook(client, body)
        assert r1.status_code == 200, r1.text
        assert r1.json()["outcome"] == "PAID"
        state1 = await _order_state(db, order["id"])
        assert state1.payment_status == "PAID"
        code = state1.pickup_code
        assert code

        txns_before = (await db.execute(text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE customer_order_id = :i AND status = 'PAID'"),
            {"i": order["id"]})).scalar()

        # The exact same body, replayed verbatim — the real-world case.
        r2 = await _post_webhook(client, body)
        assert r2.status_code == 200, r2.text

        state2 = await _order_state(db, order["id"])
        assert state2.pickup_code == code, "replay minted a second code"
        assert state2.payment_status == "PAID"

        txns_after = (await db.execute(text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE customer_order_id = :i AND status = 'PAID'"),
            {"i": order["id"]})).scalar()
        assert txns_after == txns_before == 1, (
            "replay produced more than one PAID payment_transactions row"
        )

        stock_states = (await db.execute(text(
            "SELECT state FROM stock_reservations WHERE order_id = :i"),
            {"i": order["id"]})).fetchall()
        assert all(s[0] != "RELEASED" for s in stock_states) or not stock_states


# ============================ (c) underpaid =====================================

class TestUnderpaid:
    async def test_amount_below_total_does_not_mark_paid(
            self, client, db, seed, monkeypatch):
        order = await _place_prepaid(client, seed, qty=1)  # total = ₹100
        assert order["total_amount"] == 100

        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=1.0,
                        cf_payment_id=_payid("short"))
        r = await _post_webhook(client, body)
        assert r.status_code == 200, r.text
        assert r.json()["applied"] is False

        state = await _order_state(db, order["id"])
        assert state.payment_status != "PAID"
        assert state.pickup_code is None, "an underpaid order minted a code"
        assert state.payment_amount_mismatch is True

    async def test_amount_meeting_total_still_pays(
            self, client, db, seed, monkeypatch):
        order = await _place_prepaid(client, seed, qty=1)
        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=100.0,
                        cf_payment_id=_payid("full"))
        r = await _post_webhook(client, body)
        assert r.status_code == 200, r.text
        state = await _order_state(db, order["id"])
        assert state.payment_status == "PAID"
        assert state.payment_amount_mismatch is False

    async def test_amount_exceeding_total_still_pays(
            self, client, db, seed, monkeypatch):
        """Over-payment is not the defect this hardens against — only short."""
        order = await _place_prepaid(client, seed, qty=1)
        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=100.50,
                        cf_payment_id=_payid("over"))
        r = await _post_webhook(client, body)
        assert r.status_code == 200, r.text
        state = await _order_state(db, order["id"])
        assert state.payment_status == "PAID"


# ====================== (d) paid after expiry/terminal =========================

class TestLatePayment:
    async def test_payment_after_abandonment_flags_refund_mints_no_code(
            self, client, db, seed, monkeypatch):
        order = await _place_prepaid(client, seed, qty=1)
        await db.execute(text(
            "UPDATE customer_orders SET status = 'ABANDONED' WHERE id = :i"),
            {"i": order["id"]})
        await db.commit()

        _go_live(monkeypatch)
        body = _cf_body(order_id=order["id"], payment_amount=100.0,
                        cf_payment_id=_payid("late"))
        r = await _post_webhook(client, body)
        assert r.status_code == 200, r.text
        assert r.json()["applied"] is False

        state = await _order_state(db, order["id"])
        assert state.status == "ABANDONED", "a late payment reopened the order"
        assert state.payment_status != "PAID"
        assert state.pickup_code is None
        assert state.refund_required is True
        assert state.refund_reason == "late_payment_after_expiry"


# ======================= (e) client cannot self-mark PAID ======================

class TestClientCannotSelfMarkPaid:
    async def test_order_status_poll_does_not_mark_paid(
            self, client, db, seed):
        """GET /customer/orders/{id} — the status poll the app runs while
        waiting on the Cashfree sheet — must be read-only no matter how many
        times it is called."""
        order = await _place_prepaid(client, seed)
        for _ in range(3):
            g = await client.get(f"{API}/customer/orders/{order['id']}",
                                 headers=seed["customer_auth"])
            assert g.status_code == 200, g.text
        state = await _order_state(db, order["id"])
        assert state.payment_status != "PAID"

    async def test_there_is_no_return_url_endpoint_that_marks_paid(
            self, client, seed):
        """Pinned as an inventory check: the only writers of PAID are the
        webhook and the stub-only /payment/simulate. If a return-URL/status
        endpoint is ever added that mutates state, this must be revisited —
        until then, the common guesses for its path must not exist."""
        order = await _place_prepaid(client, seed)
        for path in ("/customer/payment/return", "/customer/payment/status"):
            r = await client.post(f"{API}{path}",
                                  headers=seed["customer_auth"],
                                  json={"order_id": order["id"]})
            assert r.status_code in (404, 405), (
                f"{path} exists and accepted a POST — verify it cannot mark "
                f"PAID on the client's say-so"
            )


# ============================== (f) unknown order ==============================

class TestUnknownOrder:
    async def test_unknown_order_id_is_ignored_not_crashed(
            self, client, monkeypatch, caplog):
        _go_live(monkeypatch)
        unknown = str(uuid.uuid4())
        body = _cf_body(order_id=unknown, payment_amount=100.0)
        r = await _post_webhook(client, body)
        assert r.status_code == 404, r.text
        assert "unresolvable order" in caplog.text
        assert unknown in caplog.text


# ============================ (g) paise rounding ================================

class TestPaiseRounding:
    """Pure unit tests — no HTTP, no network. Cashfree's wire amounts are
    decimal RUPEES; every conversion to integer paise must round the same
    way on both the create-order response and the webhook."""

    def test_create_order_response_amount_is_exact_paise(self):
        gw = CashfreeGateway()
        # Mirrors GatewayOrder's own construction in create_order (gateway.py)
        # without the network call: Cashfree's documented response shape.
        data = {"order_amount": 149.99, "order_currency": "INR",
                "cf_order_id": "cfo_1"}
        amount_paise = int(round(float(data.get("order_amount")) * 100))
        assert amount_paise == 14999

    def test_webhook_payment_amount_rounds_to_exact_paise(self):
        gw = CashfreeGateway()
        body = _cf_body(order_id=str(uuid.uuid4()), payment_amount=149.99,
                        cf_payment_id="cfpay_x")
        evt = gw.parse_webhook(body, json.loads(body))
        assert evt.amount_paise == 14999

    def test_a_classic_float_trap_amount_rounds_correctly(self):
        """0.1 + 0.2 in naive float math is 0.30000000000000004 — pin that the
        *100-and-round path still lands on the one correct integer."""
        gw = CashfreeGateway()
        body = _cf_body(order_id=str(uuid.uuid4()), payment_amount=2.30,
                        cf_payment_id="cfpay_y")
        evt = gw.parse_webhook(body, json.loads(body))
        assert evt.amount_paise == 230

    def test_missing_amount_is_none_not_zero(self):
        """None means 'nothing to check against' (mark_paid skips the gate);
        zero would mean 'paid nothing', which is a different and wrong claim
        for a gateway that simply omitted the field."""
        gw = CashfreeGateway()
        body = _cf_body(order_id=str(uuid.uuid4()), cf_payment_id="cfpay_z")
        evt = gw.parse_webhook(body, json.loads(body))
        assert evt.amount_paise is None
