"""TASK 3 — carevo_payments.adapters: provider-independent webhook
verification.

Pure unit tests against the adapters directly, no HTTP and no DB. Secrets
used here are literals generated for this test file only, never read from
any real .env.

Cashfree coverage here is ADDITIONAL to, not a replacement for, the existing
route-level tests (test_api_webhook_cross_order.py,
test_api_webhook_replay_window.py, test_api_webhook_concurrency.py,
test_api_payment_webhook_auth.py, test_api_cashfree_hardening.py) — those
exercise /customer/payment/webhook end to end and are untouched by this task,
proving CashfreeAdapter's existence changed nothing about that route.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.core.config import settings
from app.modules.carevo_payments import adapters as ad

CF_SECRET = "whsec_adapter_test_only"
RZP_SECRET = "rzp_whsec_adapter_test_only"


# ============================== Cashfree ====================================

def _cf_sign(body: bytes, timestamp: str, secret: str = CF_SECRET) -> str:
    signed = f"{timestamp}{body.decode()}".encode()
    return base64.b64encode(
        hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()


def _cf_body(order_id: str = "order-abc", amount: float = 100.0) -> bytes:
    return json.dumps({
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"payment_status": "SUCCESS",
                        "payment_amount": amount,
                        "cf_payment_id": "cfpay_adapter_test",
                        "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
        },
    }, separators=(",", ":")).encode()


@pytest.fixture
def cashfree_adapter(monkeypatch):
    from app.modules.carevo_payments.gateway import CashfreeGateway
    gw = CashfreeGateway()
    monkeypatch.setattr(gw, "secret_key", CF_SECRET)
    return ad.CashfreeAdapter(gateway=gw, max_age_s=7200)


class TestCashfreeAdapter:
    def test_valid_signature_and_timestamp_verifies(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()))
        evt = cashfree_adapter.verify(body, {
            "x-webhook-signature": _cf_sign(body, ts),
            "x-webhook-timestamp": ts,
        })
        assert evt.provider == "cashfree"
        assert evt.status == "PAID"
        assert evt.order_ref == "order-abc"
        assert evt.provider_payment_id == "cfpay_adapter_test"

    def test_body_altered_by_one_byte_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()))
        sig = _cf_sign(body, ts)
        tampered = bytearray(body)
        tampered[-2] ^= 0x01
        with pytest.raises(ad.InvalidSignatureError):
            cashfree_adapter.verify(bytes(tampered), {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_whitespace_altered_body_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()))
        sig = _cf_sign(body, ts)
        # Re-serialise with different spacing — same JSON value, different
        # bytes. The signature was computed over the ORIGINAL bytes.
        reserialized = json.dumps(json.loads(body), indent=2).encode()
        with pytest.raises(ad.InvalidSignatureError):
            cashfree_adapter.verify(reserialized, {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_wrong_secret_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()))
        sig = _cf_sign(body, ts, secret="a-different-secret-entirely")
        with pytest.raises(ad.InvalidSignatureError):
            cashfree_adapter.verify(body, {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_missing_signature_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()))
        with pytest.raises(ad.MissingSignatureError):
            cashfree_adapter.verify(body, {"x-webhook-timestamp": ts})

    def test_missing_timestamp_fails(self, cashfree_adapter):
        body = _cf_body()
        sig = _cf_sign(body, "")  # Cashfree signs timestamp+body; empty ts
        with pytest.raises((ad.MissingTimestampError, ad.InvalidSignatureError)):
            cashfree_adapter.verify(body, {"x-webhook-signature": sig})

    def test_non_numeric_timestamp_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = "not-a-number"
        sig = _cf_sign(body, ts)
        with pytest.raises(ad.InvalidTimestampError):
            cashfree_adapter.verify(body, {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_stale_timestamp_beyond_tolerance_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()) - 7201)
        sig = _cf_sign(body, ts)
        with pytest.raises(ad.StaleTimestampError):
            cashfree_adapter.verify(body, {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_future_timestamp_beyond_tolerance_fails(self, cashfree_adapter):
        body = _cf_body()
        ts = str(int(time.time()) + 7201)
        sig = _cf_sign(body, ts)
        with pytest.raises(ad.StaleTimestampError):
            cashfree_adapter.verify(body, {
                "x-webhook-signature": sig, "x-webhook-timestamp": ts,
            })

    def test_oversized_body_rejected_before_parsing(self, cashfree_adapter):
        huge = b"x" * (ad.MAX_WEBHOOK_BODY_BYTES + 1)
        with pytest.raises(ad.BodyTooLargeError):
            cashfree_adapter.verify(huge, {
                "x-webhook-signature": "irrelevant",
                "x-webhook-timestamp": str(int(time.time())),
            })


# ============================== Razorpay ====================================

def _rzp_sign(body: bytes, secret: str = RZP_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _rzp_body(order_id: str = "order_abc", amount: int = 10000) -> bytes:
    return json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_adapter_test", "order_id": order_id,
            "status": "captured", "amount": amount, "currency": "INR",
        }}},
    }, separators=(",", ":")).encode()


def _rzp_body_with_created_at(created_at: int, order_id: str = "order_abc",
                               amount: int = 10000) -> bytes:
    return json.dumps({
        "event": "payment.captured",
        "created_at": created_at,
        "payload": {"payment": {"entity": {
            "id": "pay_adapter_test", "order_id": order_id,
            "status": "captured", "amount": amount, "currency": "INR",
        }}},
    }, separators=(",", ":")).encode()


@pytest.fixture
def razorpay_adapter(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", RZP_SECRET)
    return ad.RazorpayWebhookAdapter(secret=RZP_SECRET, max_age_s=7200)


class TestRazorpayAdapter:
    def test_signature_and_event_id_only_is_accepted(self, razorpay_adapter):
        """The real-delivery shape: only X-Razorpay-Signature and
        x-razorpay-event-id, no timestamp header of any kind -- the
        fabricated X-Razorpay-Event-Timestamp requirement is gone."""
        body = _rzp_body()
        evt = razorpay_adapter.verify(body, {
            "X-Razorpay-Signature": _rzp_sign(body),
            "x-razorpay-event-id": "evt_adapter_test",
        })
        assert evt.provider == "razorpay_webhook"
        assert evt.status == "PAID"
        assert evt.order_ref == "order_abc"
        assert evt.provider_payment_id == "pay_adapter_test"
        assert evt.event_id == "evt_adapter_test"
        assert evt.amount_paise == 10000

    def test_missing_event_id_falls_back_to_body_hash(self, razorpay_adapter):
        body = _rzp_body()
        evt = razorpay_adapter.verify(body, {
            "X-Razorpay-Signature": _rzp_sign(body),
        })
        assert evt.event_id == f"body:{hashlib.sha256(body).hexdigest()}"

    def test_body_altered_by_one_byte_fails(self, razorpay_adapter):
        body = _rzp_body()
        sig = _rzp_sign(body)
        tampered = bytearray(body)
        tampered[-2] ^= 0x01
        with pytest.raises(ad.InvalidSignatureError):
            razorpay_adapter.verify(bytes(tampered), {
                "X-Razorpay-Signature": sig,
            })

    def test_whitespace_altered_body_fails(self, razorpay_adapter):
        body = _rzp_body()
        sig = _rzp_sign(body)
        reserialized = json.dumps(json.loads(body), indent=2).encode()
        with pytest.raises(ad.InvalidSignatureError):
            razorpay_adapter.verify(reserialized, {
                "X-Razorpay-Signature": sig,
            })

    def test_wrong_secret_fails(self, razorpay_adapter):
        body = _rzp_body()
        sig = _rzp_sign(body, secret="a-different-secret-entirely")
        with pytest.raises(ad.InvalidSignatureError):
            razorpay_adapter.verify(body, {
                "X-Razorpay-Signature": sig,
            })

    def test_missing_signature_fails(self, razorpay_adapter):
        body = _rzp_body()
        with pytest.raises(ad.MissingSignatureError):
            razorpay_adapter.verify(body, {})

    def test_no_timestamp_header_of_any_kind_is_required(self, razorpay_adapter):
        """A real Razorpay delivery sends no timestamp header at all; this
        must verify, not raise MissingTimestampError."""
        body = _rzp_body()
        sig = _rzp_sign(body)
        evt = razorpay_adapter.verify(body, {"X-Razorpay-Signature": sig})
        assert evt.status == "PAID"

    def test_present_but_stale_created_at_in_the_payload_is_rejected(
            self, razorpay_adapter):
        body = _rzp_body_with_created_at(int(time.time()) - 7201)
        sig = _rzp_sign(body)
        with pytest.raises(ad.StaleTimestampError):
            razorpay_adapter.verify(body, {"X-Razorpay-Signature": sig})

    def test_present_but_future_created_at_in_the_payload_is_rejected(
            self, razorpay_adapter):
        body = _rzp_body_with_created_at(int(time.time()) + 7201)
        sig = _rzp_sign(body)
        with pytest.raises(ad.StaleTimestampError):
            razorpay_adapter.verify(body, {"X-Razorpay-Signature": sig})

    def test_present_and_fresh_created_at_in_the_payload_is_accepted(
            self, razorpay_adapter):
        body = _rzp_body_with_created_at(int(time.time()))
        sig = _rzp_sign(body)
        evt = razorpay_adapter.verify(body, {"X-Razorpay-Signature": sig})
        assert evt.status == "PAID"

    def test_absent_created_at_never_causes_a_rejection(self, razorpay_adapter):
        """_rzp_body() carries no top-level created_at at all -- confirms
        the optional check never rejects for ABSENCE, only for presence
        plus an out-of-window value."""
        body = _rzp_body()
        assert "created_at" not in json.loads(body)
        sig = _rzp_sign(body)
        evt = razorpay_adapter.verify(body, {"X-Razorpay-Signature": sig})
        assert evt.status == "PAID"

    def test_missing_secret_fails_closed(self):
        adapter = ad.RazorpayWebhookAdapter(secret=None, max_age_s=7200)
        body = _rzp_body()
        with pytest.raises(ad.AdapterConfigError):
            adapter.verify(body, {
                "X-Razorpay-Signature": "irrelevant",
            })


# ============================== Registry ====================================

class TestGetAdapterRegistry:
    def test_cashfree_always_returns_an_adapter(self):
        adapter = ad.get_adapter("cashfree")
        assert isinstance(adapter, ad.CashfreeAdapter)
        assert adapter.production_eligible is True

    def test_razorpay_disabled_by_default_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "RAZORPAY_ADAPTER_ENABLED", False)
        with pytest.raises(ad.AdapterConfigError):
            ad.get_adapter("razorpay")

    def test_razorpay_enabled_returns_a_production_eligible_adapter(self, monkeypatch):
        monkeypatch.setattr(settings, "RAZORPAY_ADAPTER_ENABLED", True)
        adapter = ad.get_adapter("razorpay")
        assert isinstance(adapter, ad.RazorpayWebhookAdapter)
        assert adapter.production_eligible is True

    def test_unknown_provider_raises(self):
        with pytest.raises(ad.AdapterConfigError):
            ad.get_adapter("some-other-gateway")
