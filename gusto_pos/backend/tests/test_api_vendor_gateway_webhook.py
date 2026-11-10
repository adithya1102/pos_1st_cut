"""TASK 5 — vendor-direct gateway webhook route + admin credential route.

HTTP-level tests via the real ASGI app (tests/conftest.py's `client` and
`seed` fixtures). Secrets used here are generated in memory by this file,
never read from any real .env.
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


class TestFlagOff:
    @pytest.mark.asyncio
    async def test_flag_off_returns_404(self, client, monkeypatch, seed):
        monkeypatch.setattr(settings, "VENDOR_GATEWAY_ENABLED", False)
        r = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}",
            content=b"{}", headers={"content-type": "application/json"})
        assert r.status_code == 404


class TestEnumerationSafety:
    @pytest.mark.asyncio
    async def test_unknown_outlet_equals_wrong_signature_same_status_and_body(
        self, client, db, seed
    ):
        secret = "outlet-secret-for-enum-test"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))

        # Case A: outlet does not exist at all.
        r_unknown = await client.post(
            f"{API}/webhooks/cashfree/{uuid.uuid4()}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret),
                     "x-webhook-timestamp": ts})

        # Case B: outlet exists, but the signature is wrong.
        r_wrong_sig = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, "a-totally-different-secret"),
                     "x-webhook-timestamp": ts})

        assert r_unknown.status_code == r_wrong_sig.status_code == 404
        assert r_unknown.json() == r_wrong_sig.json()

    @pytest.mark.asyncio
    async def test_malformed_outlet_id_also_matches(self, client):
        r = await client.post(
            f"{API}/webhooks/cashfree/not-a-uuid-at-all", content=b"{}",
            headers={"content-type": "application/json"})
        assert r.status_code == 404
        assert r.json() == {"detail": "Not Found"}


class TestValidDeliveryApplies:
    @pytest.mark.asyncio
    async def test_a_correctly_signed_delivery_is_applied(self, client, db, seed):
        secret = "outlet-secret-for-valid-delivery"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret)
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            total_amount=100.0)

        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))
        r = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret),
                     "x-webhook-timestamp": ts})
        assert r.status_code == 200, r.text
        assert r.json()["outcome"] == "APPLIED"

        confirmed_at = await db.scalar(text(
            "SELECT vendor_payment_confirmed_at FROM customer_orders WHERE id = :id"),
            {"id": order_id})
        assert confirmed_at is not None


class TestCrossOutletSecret:
    @pytest.mark.asyncio
    async def test_cross_outlet_secret_does_not_verify(self, client, db, seed):
        # Two outlets, two DIFFERENT secrets.
        secret_a = "outlet-a-secret"
        secret_b = "outlet-b-secret"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", secret_a)

        other_org, other_outlet = uuid.uuid4(), uuid.uuid4()
        await db.execute(text(
            "INSERT INTO organizations (id, name, created_at) VALUES (:i,:n, now())"),
            {"i": str(other_org), "n": "Other Org"})
        await db.execute(text("""
            INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                                 upi_id, geofence_radius_meters, verification_status,
                                 created_at, cashfree_unlocked)
            VALUES (:i,:o,'Other Outlet','Testville', true, 'other@upi', 150,
                    'active', now(), true)"""),
            {"i": str(other_outlet), "o": str(other_org)})
        await db.commit()
        await vc.set_secret(db, str(other_outlet), "cashfree", secret_b)

        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])
        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))

        # Signed with outlet A's secret, posted to outlet A's own URL --
        # must verify.
        r_correct = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret_a),
                     "x-webhook-timestamp": ts})
        assert r_correct.status_code == 200, r_correct.text

        # Signed with outlet B's secret, posted to outlet A's URL -- must
        # fail, even though outlet B's secret is a REAL, active secret.
        r_cross = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, secret_b),
                     "x-webhook-timestamp": ts})
        assert r_cross.status_code == 404


class TestRotation:
    @pytest.mark.asyncio
    async def test_rotated_secret_invalidates_the_old_one(self, client, db, seed):
        old_secret = "pre-rotation-secret"
        new_secret = "post-rotation-secret"
        await vc.set_secret(db, seed["outlet_id"], "cashfree", old_secret)

        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"])

        await vc.set_secret(db, seed["outlet_id"], "cashfree", new_secret)

        body = _cf_body(order_id, 100.0)
        ts = str(int(time.time()))
        r_old = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, old_secret),
                     "x-webhook-timestamp": ts})
        assert r_old.status_code == 404

        r_new = await client.post(
            f"{API}/webhooks/cashfree/{seed['outlet_id']}", content=body,
            headers={"content-type": "application/json",
                     "x-webhook-signature": _cf_sign(body, ts, new_secret),
                     "x-webhook-timestamp": ts})
        assert r_new.status_code == 200, r_new.text


class TestAdminCredentialRouteNeverLeaksSecret:
    @pytest.mark.asyncio
    async def test_set_credential_response_never_contains_the_secret(
        self, client, seed
    ):
        secret = "THIS-SECRET-MUST-NEVER-COME-BACK-IN-ANY-RESPONSE"
        r = await client.put(
            f"{API}/admin/vendor-gateway/outlets/{seed['outlet_id']}/credentials/cashfree",
            headers=seed["admin_auth"], json={"secret": secret})
        assert r.status_code == 200, r.text
        assert secret not in r.text

    @pytest.mark.asyncio
    async def test_set_credential_requires_super_admin(self, client, seed):
        r = await client.put(
            f"{API}/admin/vendor-gateway/outlets/{seed['outlet_id']}/credentials/cashfree",
            headers=seed["owner_auth"], json={"secret": "whatever"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_set_credential_logged_output_never_contains_the_secret(
        self, client, seed, caplog
    ):
        secret = "THIS-SECRET-MUST-NEVER-APPEAR-IN-ANY-LOG-LINE"
        with caplog.at_level("DEBUG"):
            r = await client.put(
                f"{API}/admin/vendor-gateway/outlets/{seed['outlet_id']}/credentials/cashfree",
                headers=seed["admin_auth"], json={"secret": secret})
        assert r.status_code == 200, r.text
        assert secret not in caplog.text
