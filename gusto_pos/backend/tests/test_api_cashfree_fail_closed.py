"""Task 1 — fail-closed payment configuration.

LITERAL BEHAVIOUR BEFORE THIS FILE (and before config.py/main.py changed):

  (a) No startup validation existed. CASHFREE_ONLY=true with PAYMENT_GATEWAY
      left at anything but "cashfree", or with a Cashfree credential missing,
      booted the process successfully — main.py's on_startup ran init_db and
      nothing else checked this combination. The misconfiguration only
      surfaced indirectly, per request: payment_methods_for (carevo_customer/
      service.py) just resolves to an empty method list. THIS IS THE ONE
      CODE CHANGE this file covers: app/core/config.py now defines
      validate_cashfree_only_config()/PaymentConfigError, called from
      app/main.py's on_startup before init_db().

  (b) /customer/payment/simulate ALREADY gated on
      `settings.PAYMENT_GATEWAY != "stub"` -> 403
      (carevo_customer/controller.py:719, pre-existing). No code change;
      this file adds the explicit both-values regression the task asked for.

  (c) /customer/payment/webhook ALREADY failed closed when the signing secret
      is unset: CashfreeGateway.verify_webhook_signature returns False when
      self.secret_key is falsy (carevo_payments/gateway.py:553), so the
      endpoint answers 400 "Invalid webhook signature" and never reaches
      mark_paid. Previously pinned only as a unit test on the verifier
      itself (test_api_payment_webhook_auth.py::
      test_cashfree_verifier_fails_closed_on_missing_pieces). No code change;
      this file adds the end-to-end HTTP case against a REAL order and proves
      the row is byte-for-byte unchanged.

The literal setting used to tell a test environment from a real one:
APP_ENV == "test" (tests/conftest.py sets this before the app is imported).
Any other value, including the unset default ("production" — the same
default main.py's _DOCS_ENABLED already uses), is treated as real.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.core.config import (
    PaymentConfigError,
    settings,
    validate_cashfree_only_config,
)
from tests.conftest import API


# ============================ (a) startup validation ==========================

class TestStartupFailsClosed:
    def test_cashfree_only_false_never_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", False)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", None)
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", None)
        validate_cashfree_only_config(env_name="production")

    def test_wrong_gateway_refuses_to_start(self, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "razorpay")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", "app-id-value")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", "secret-value")
        with pytest.raises(PaymentConfigError) as exc:
            validate_cashfree_only_config(env_name="production")
        assert "PAYMENT_GATEWAY" in str(exc.value)

    def test_missing_app_id_names_the_variable_not_the_value(self, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", None)
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", "super-secret-value")
        with pytest.raises(PaymentConfigError) as exc:
            validate_cashfree_only_config(env_name="production")
        msg = str(exc.value)
        assert "CASHFREE_APP_ID" in msg
        assert "super-secret-value" not in msg, "a credential VALUE leaked into the error"

    def test_missing_secret_key_names_the_variable(self, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", "app-id-value")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", None)
        with pytest.raises(PaymentConfigError) as exc:
            validate_cashfree_only_config(env_name="production")
        assert "CASHFREE_SECRET_KEY" in str(exc.value)
        assert "app-id-value" not in str(exc.value)

    def test_fully_configured_passes(self, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", "app-id-value")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", "secret-value")
        validate_cashfree_only_config(env_name="production")

    def test_test_environment_is_exempt_even_when_misconfigured(self, monkeypatch):
        """The literal exemption: APP_ENV == 'test'. A test that monkeypatches
        CASHFREE_ONLY=true for one assertion (test_api_cashfree_only.py does
        this throughout) is not restarting the process, so it must never be
        able to trip this."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "razorpay")
        monkeypatch.setattr(settings, "CASHFREE_APP_ID", None)
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", None)
        validate_cashfree_only_config(env_name="test")

    def test_default_env_name_reads_the_live_app_env(self, monkeypatch):
        """No env_name passed -> reads os.environ["APP_ENV"], exactly as the
        app/main.py startup hook calls it."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "razorpay")
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(PaymentConfigError):
            validate_cashfree_only_config()


# ============================ (b) simulate route gating =======================

class TestSimulateRouteGating:
    """Pre-existing guard (controller.py:719) — PAYMENT_GATEWAY decides
    reachability, not authentication. Both literal values asserted."""

    async def test_simulate_reachable_under_stub_gateway(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json={
                                  "outlet_id": seed["outlet_id"],
                                  "items": [{"menu_item_id": seed["menu_item_id"],
                                             "quantity": 1}],
                              })
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]

        sim = await client.post(f"{API}/customer/payment/simulate",
                                headers=seed["customer_auth"],
                                json={"order_id": order_id, "method": "upi"})
        assert sim.status_code == 200, sim.text

    async def test_simulate_unreachable_under_cashfree_gateway(
            self, client, seed, monkeypatch):
        # Order created under the stub (conftest default) so no network call
        # is ever made to Cashfree — only the /simulate POST runs live-gated.
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json={
                                  "outlet_id": seed["outlet_id"],
                                  "items": [{"menu_item_id": seed["menu_item_id"],
                                             "quantity": 1}],
                              })
        assert r.status_code == 200, r.text
        order_id = r.json()["id"]

        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        sim = await client.post(f"{API}/customer/payment/simulate",
                                headers=seed["customer_auth"],
                                json={"order_id": order_id, "method": "upi"})
        assert sim.status_code in (403, 404), sim.text


# ============================ (c) webhook, secret unset ========================

class TestWebhookSecretUnset:
    async def test_webhook_rejected_and_order_unchanged_when_secret_unset(
            self, client, db, seed, monkeypatch):
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"], json={
                                  "outlet_id": seed["outlet_id"],
                                  "items": [{"menu_item_id": seed["menu_item_id"],
                                             "quantity": 1}],
                              })
        assert r.status_code == 200, r.text
        order = r.json()

        before = (await db.execute(text(
            "SELECT status, payment_status, pickup_code FROM customer_orders "
            "WHERE id = :i"), {"i": order["id"]})).first()

        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", None)

        body = json.dumps({
            "type": "PAYMENT_SUCCESS_WEBHOOK",
            "data": {
                "order": {"order_id": order["id"]},
                "payment": {"payment_status": "SUCCESS",
                           "payment_amount": order["total_amount"],
                           "cf_payment_id": "cfpay_nosecret_test",
                           "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
            },
        }).encode()

        resp = await client.post(
            f"{API}/customer/payment/webhook", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": "whatever-this-cannot-verify",
                     "x-webhook-timestamp": "1700000000"},
        )
        assert resp.status_code == 400, resp.text

        after = (await db.execute(text(
            "SELECT status, payment_status, pickup_code FROM customer_orders "
            "WHERE id = :i"), {"i": order["id"]})).first()
        assert after == before, "order changed despite an unverifiable webhook"
