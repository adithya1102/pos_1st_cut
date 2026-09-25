"""The payment webhook must never take a caller's word that money moved.

Regression cover for the audit's Critical finding on
POST /customer/payment/webhook. Before this, StubRazorpayGateway's verifier
returned True whenever RAZORPAY_WEBHOOK_SECRET was unset — which is every
deploy that has not deliberately set it, including production — and
parse_webhook resolved outcome=PAID from the mere presence of an `order_id`.

The whole exploit was therefore:

    POST /api/v1/customer/payment/webhook
    {"order_id": "<the caller's own order>"}

with no credential and no signature, yielding a pickup code, loyalty points,
and a kitchen ticket for an order nobody paid for.

Two independent guards are asserted here, because either alone would have
closed this and both are worth keeping:

  1. the endpoint refuses outright unless a LIVE gateway is configured, and
  2. the stub verifier fails CLOSED on a missing secret rather than open.

The suite runs with PAYMENT_GATEWAY=stub (conftest), so guard 1 is what these
requests hit. Guard 2 is asserted directly against the gateway object, since
no HTTP path reaches it while the stub is selected.
"""
import uuid

import pytest

from app.modules.carevo_payments.gateway import (
    CashfreeGateway,
    StubRazorpayGateway,
    get_gateway,
)
from tests.conftest import API


# --------------------------------------------------------------------------
# Guard 1 — the endpoint, over HTTP
# --------------------------------------------------------------------------
UNSIGNED_BODIES = [
    pytest.param({"order_id": str(uuid.uuid4())}, id="bare-order_id"),
    pytest.param(
        {"event": "payment.captured", "order_id": str(uuid.uuid4()),
         "payload": {"payment": {"entity": {"id": "pay_x", "method": "card"}}}},
        id="razorpay-shaped",
    ),
    pytest.param({}, id="empty-body"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", UNSIGNED_BODIES)
async def test_webhook_refused_without_live_gateway(client, body):
    """No live gateway => 503, whatever the body looks like."""
    r = await client.post(f"{API}/customer/payment/webhook", json=body)
    assert r.status_code == 503, (
        f"unsigned webhook answered {r.status_code} under the stub gateway — "
        f"this endpoint must not accept a body it cannot authenticate"
    )


@pytest.mark.asyncio
async def test_webhook_refused_even_with_a_made_up_signature(client):
    """Inventing a signature header does not help — the refusal is before it."""
    r = await client.post(
        f"{API}/customer/payment/webhook",
        json={"order_id": str(uuid.uuid4())},
        headers={"X-Razorpay-Signature": "deadbeef",
                 "x-webhook-signature": "deadbeef",
                 "x-webhook-timestamp": "1700000000"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_webhook_cannot_mark_a_real_order_paid(client, seed):
    """The exploit, end to end, against a REAL unpaid order of the caller's.

    The order id is genuine and the request is otherwise well-formed, so this
    is the actual attack rather than a shape test. It must not move the order.
    """
    r = await client.post(
        f"{API}/customer/orders",
        headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"],
              "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]},
    )
    assert r.status_code in (200, 201), r.text
    order_id = r.json()["id"]

    before = await client.get(f"{API}/customer/orders/{order_id}",
                              headers=seed["customer_auth"])
    assert before.json()["payment_status"] != "PAID"

    hook = await client.post(f"{API}/customer/payment/webhook",
                             json={"order_id": order_id})
    assert hook.status_code == 503, "the free-order webhook is open again"

    after = await client.get(f"{API}/customer/orders/{order_id}",
                             headers=seed["customer_auth"])
    assert after.json()["payment_status"] != "PAID", (
        "an unsigned webhook marked a real order PAID — this is the exact "
        "free-money path the guard exists to close"
    )
    assert not after.json().get("pickup_code"), "unpaid order was issued a pickup code"


# --------------------------------------------------------------------------
# Guard 2 — the verifier itself, directly
# --------------------------------------------------------------------------
def test_stub_verifier_fails_closed_without_a_secret():
    """The regression that mattered: missing secret must deny, not admit."""
    gw = StubRazorpayGateway()
    gw.webhook_secret = None
    assert gw.verify_webhook_signature(b'{"order_id":"x"}', None) is False
    assert gw.verify_webhook_signature(b'{"order_id":"x"}', "anything") is False
    gw.webhook_secret = ""
    assert gw.verify_webhook_signature(b'{"order_id":"x"}', "anything") is False


def test_stub_verifier_still_accepts_a_correctly_signed_body():
    """Failing closed must not mean failing always — a real HMAC still passes."""
    import hashlib
    import hmac as _hmac

    gw = StubRazorpayGateway()
    gw.webhook_secret = "s3cr3t"
    body = b'{"order_id":"abc"}'
    good = _hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert gw.verify_webhook_signature(body, good) is True
    assert gw.verify_webhook_signature(body, good[:-1] + "0") is False
    assert gw.verify_webhook_signature(b'{"order_id":"tampered"}', good) is False


def test_cashfree_verifier_fails_closed_on_missing_pieces():
    """Unchanged behaviour, pinned so the two verifiers cannot diverge again."""
    gw = CashfreeGateway()
    gw.secret_key = None
    assert gw.verify_webhook_signature(b"{}", "sig", timestamp="1") is False
    gw.secret_key = "k"
    assert gw.verify_webhook_signature(b"{}", None, timestamp="1") is False
    assert gw.verify_webhook_signature(b"{}", "sig", timestamp=None) is False


def test_liveness_flags():
    """`is_live` is what the endpoint gates on — pin both ends of it."""
    assert StubRazorpayGateway().is_live is False
    assert CashfreeGateway().is_live is True
    # conftest sets PAYMENT_GATEWAY=stub, so the factory must yield the stub.
    assert get_gateway().is_live is False
