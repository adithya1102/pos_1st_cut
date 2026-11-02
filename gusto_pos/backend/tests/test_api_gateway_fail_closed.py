"""Task 2 — fail-closed gateway posture, independent of CASHFREE_ONLY.

Before this file: a non-cashfree PAYMENT_GATEWAY (including the "unset"
default) could boot in any environment, including production, with nothing
to stop it — the only startup check was validate_cashfree_only_config, and it
is a no-op whenever CASHFREE_ONLY is false. That is exactly how 71
payment_transactions rows shipped with gateway='razorpay' on 2026-09-08 (see
config.py's PAYMENT_GATEWAY comment).

validate_gateway_startup_posture (app/core/config.py) now refuses to let the
process start in that shape unless ALLOW_STUB_GATEWAY=true is set explicitly.
NON_PRODUCTION_ENVS (app/core/config.py) is the one constant shared by this
check and app/main.py's docs-enablement check.

The simulate route (/customer/payment/simulate) is additionally gated the
same way, on top of its pre-existing PAYMENT_GATEWAY == "stub" guard.
"""
from __future__ import annotations

import logging

import pytest

from app.core.config import (
    NON_PRODUCTION_ENVS,
    PaymentConfigError,
    settings,
    validate_gateway_startup_posture,
)
from tests.conftest import API


# ======================== startup posture (Task 2b) ===========================

class TestGatewayStartupPosture:
    def test_unset_gateway_in_production_env_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        with pytest.raises(PaymentConfigError) as exc:
            validate_gateway_startup_posture(env_name="production", allow_stub="")
        assert "PAYMENT_GATEWAY" in str(exc.value)

    def test_cashfree_in_production_env_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        validate_gateway_startup_posture(env_name="production", allow_stub="")

    def test_stub_with_allow_stub_gateway_true_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        validate_gateway_startup_posture(env_name="production", allow_stub="true")

    def test_stub_in_a_dev_env_starts(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        for env in NON_PRODUCTION_ENVS:
            validate_gateway_startup_posture(env_name=env, allow_stub="")

    def test_stub_without_the_flag_in_production_still_refuses(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        with pytest.raises(PaymentConfigError):
            validate_gateway_startup_posture(env_name="production", allow_stub="")

    def test_allow_stub_gateway_is_case_insensitive_literal_true_only(
            self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        validate_gateway_startup_posture(env_name="production", allow_stub="TRUE")
        with pytest.raises(PaymentConfigError):
            validate_gateway_startup_posture(env_name="production", allow_stub="1")

    def test_applies_regardless_of_cashfree_only(self, monkeypatch):
        # The task is explicit: this check fires whether CASHFREE_ONLY is on
        # or off. CASHFREE_ONLY is not even read by the function — assert
        # both positions still refuse an unset gateway in production.
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        for cashfree_only in (True, False):
            monkeypatch.setattr(settings, "CASHFREE_ONLY", cashfree_only)
            with pytest.raises(PaymentConfigError):
                validate_gateway_startup_posture(env_name="production", allow_stub="")

    def test_default_env_name_reads_the_live_app_env(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("ALLOW_STUB_GATEWAY", raising=False)
        with pytest.raises(PaymentConfigError):
            validate_gateway_startup_posture()

    def test_default_allow_stub_reads_the_live_env_var(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ALLOW_STUB_GATEWAY", "true")
        validate_gateway_startup_posture()


# =========================== simulate route (Task 2c) ==========================

class TestSimulateRouteProductionGating:
    async def test_simulate_403_in_production_without_allow_stub(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("ALLOW_STUB_GATEWAY", raising=False)

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
        assert sim.status_code == 403, sim.text

    async def test_simulate_allowed_in_production_with_allow_stub_true(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("ALLOW_STUB_GATEWAY", "true")

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

    async def test_simulate_allowed_in_a_dev_env_without_the_flag(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "stub")
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.delenv("ALLOW_STUB_GATEWAY", raising=False)

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


# ========================= startup gateway log (Task 2d) =======================

class TestEffectiveGatewayLogged:
    def test_startup_logs_the_effective_gateway_name_once(self, caplog, monkeypatch):
        from app.modules.carevo_payments.gateway import log_effective_gateway
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", "super-secret-value")
        with caplog.at_level(logging.INFO):
            log_effective_gateway()
        gateway_lines = [r.getMessage() for r in caplog.records
                          if "Effective payment gateway:" in r.getMessage()]
        assert len(gateway_lines) == 1
        assert "cashfree" in gateway_lines[0]
        # Never a credential value, anywhere in this call's log output.
        assert not any("super-secret-value" in r.getMessage()
                       for r in caplog.records)
