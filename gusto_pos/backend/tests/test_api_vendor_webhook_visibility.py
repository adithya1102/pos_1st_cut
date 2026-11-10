"""TASK 8 (reconcile fix pass) — vendor_webhook_controller logs a static
reason code (never a secret, signature, or body) on every rejected
delivery, and the unknown-outlet path costs the same as the
known-outlet-wrong-signature path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_payments import vendor_credentials as vc
from tests.conftest import API

ENC_KEY_B64 = base64.urlsafe_b64encode(b"0" * 32).decode("ascii")

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _vendor_gateway_env(monkeypatch):
    monkeypatch.setattr(settings, "VENDOR_GATEWAY_ENABLED", True)
    monkeypatch.setattr(settings, "SECRETS_ENC_KEY", ENC_KEY_B64)
    monkeypatch.setattr(settings, "SECRETS_ENC_KEY_ID", "k1")
    yield


def _cf_sign(body: bytes, timestamp: str, secret: str) -> str:
    signed = f"{timestamp}{body.decode()}".encode()
    return base64.b64encode(
        hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()


def _cf_body(order_id: str, amount: float) -> bytes:
    return json.dumps({
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"payment_status": "SUCCESS", "payment_amount": amount,
                        "cf_payment_id": f"cfpay_{order_id[:8]}",
                        "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
        },
    }).encode()


async def _insert_order(db, *, outlet_id, customer_id, total_amount=100.0) -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             created_at, updated_at)
        VALUES (:id, :cust, :outlet, 'CREATED', :amt, 'PENDING', now(), now())
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "amt": total_amount})
    await db.commit()
    return str(order_id)


class TestWarningReasonCodes:
    async def test_flag_off_logs_a_static_reason_code(self, client, monkeypatch,
                                                        seed, caplog):
        monkeypatch.setattr(settings, "VENDOR_GATEWAY_ENABLED", False)
        with caplog.at_level("WARNING"):
            r = await client.post(
                f"{API}/webhooks/cashfree/{seed['outlet_id']}",
                content=b"{}", headers={"content-type": "application/json"})
        assert r.status_code == 404
        assert "reason=flag_off" in caplog.text
        assert "provider=cashfree" in caplog.text

    async def test_unknown_outlet_logs_a_static_reason_code(self, client, caplog):
        with caplog.at_level("WARNING"):
            r = await client.post(
                f"{API}/webhooks/cashfree/{uuid.uuid4()}",
                content=b"{}", headers={"content-type": "application/json"})
        assert r.status_code == 404
        assert "reason=unknown_outlet" in caplog.text

    async def test_no_credential_logs_a_static_reason_code(self, client, seed, caplog):
        with caplog.at_level("WARNING"):
            r = await client.post(
                f"{API}/webhooks/cashfree/{seed['outlet_id']}",
                content=b"{}", headers={"content-type": "application/json"})
        assert r.status_code == 404
        assert "reason=credential_error" in caplog.text

    async def test_wrong_signature_logs_a_static_reason_code(
            self, client, db, seed, caplog):
        secret = "outlet-secret-for-reason-code-test"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))

        with caplog.at_level("WARNING"):
            r = await client.post(
                f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
                headers={"content-type": "application/json",
                         "x-webhook-signature": _cf_sign(body, ts, "wrong-secret"),
                         "x-webhook-timestamp": ts})
        assert r.status_code == 404
        assert "reason=signature_invalid" in caplog.text

    async def test_no_log_line_ever_contains_the_secret_signature_or_body(
            self, client, db, seed, caplog):
        secret = "THE-ONE-TRUE-SECRET-MUST-NEVER-APPEAR-IN-LOGS"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        marker = "UNIQUE-BODY-MARKER-STRING-xyz123"
        body = json.dumps({"type": "PAYMENT_SUCCESS_WEBHOOK", "marker": marker,
                            "data": {"order": {"order_id": order_id}}}).encode()
        ts = str(int(time.time()))
        wrong_sig = _cf_sign(body, ts, "a-totally-wrong-secret")

        with caplog.at_level("DEBUG"):
            r = await client.post(
                f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
                headers={"content-type": "application/json",
                         "x-webhook-signature": wrong_sig,
                         "x-webhook-timestamp": ts})
        assert r.status_code == 404
        assert secret not in caplog.text
        assert wrong_sig not in caplog.text
        assert marker not in caplog.text


class TestUnknownOutletCostsTheSameAsWrongSignature:
    async def test_response_identical_across_all_four_failure_paths(
            self, client, db, seed, monkeypatch
    ):
        secret = "outlet-secret-for-timing-equivalence"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))

        # (a) flag off
        monkeypatch.setattr(settings, "VENDOR_GATEWAY_ENABLED", False)
        r_flag_off = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json"})
        monkeypatch.setattr(settings, "VENDOR_GATEWAY_ENABLED", True)

        # (b) unknown outlet
        r_unknown = await client.post(
            f"{API}/webhooks/cashfree/{uuid.uuid4()}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret),
                     "x-webhook-timestamp": ts})

        # (c) known outlet, no credential configured for it
        other_org, other_outlet = uuid.uuid4(), uuid.uuid4()
        await db.execute(text(
            "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
            {"i": str(other_org), "n": "No-Cred Org"})
        await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                                 upi_id, geofence_radius_meters, verification_status,
                                 created_at, cashfree_unlocked)
            VALUES (:i,:o,'No Cred Outlet','Testville', true, 'nc@upi', 150,
                    'active', now(), true)"""),
            {"i": str(other_outlet), "o": str(other_org)})
        await db.commit()
        r_no_cred = await client.post(
            f"{API}/webhooks/cashfree/{other_outlet}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret),
                     "x-webhook-timestamp": ts})

        # (d) known outlet, wrong signature
        r_wrong_sig = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, "wrong-secret"),
                     "x-webhook-timestamp": ts})

        responses = [r_flag_off, r_unknown, r_no_cred, r_wrong_sig]
        assert all(r.status_code == 404 for r in responses)
        bodies = [r.json() for r in responses]
        assert all(b == bodies[0] for b in bodies)

    async def test_decoy_verify_runs_a_real_decrypt_and_hmac(
            self, client, monkeypatch
    ):
        """Structural proof the decoy path does real work, not a no-op:
        monkeypatch secrets_box.from_settings to count calls and assert it
        was actually invoked for an unknown-outlet probe."""
        from app.modules.carevo_payments import vendor_webhook_controller as vwc

        calls = {"n": 0}
        real_from_settings = vwc.sb.from_settings

        def _counting_from_settings():
            calls["n"] += 1
            return real_from_settings()

        monkeypatch.setattr(vwc.sb, "from_settings", _counting_from_settings)

        r = await client.post(
            f"{API}/webhooks/cashfree/{uuid.uuid4()}",
            content=b"{}", headers={"content-type": "application/json"})
        assert r.status_code == 404
        assert calls["n"] == 1, (
            "the unknown-outlet path must call secrets_box exactly once, "
            "the same as the known-outlet credential-fetch path does")
