"""Task 3b — CASHFREE_WEBHOOK_MAX_AGE_S: reject a stale-but-validly-signed
webhook.

LITERAL BEHAVIOUR BEFORE THIS FILE: payment_webhook checked the signature and
nothing else about x-webhook-timestamp's AGE. A validly-signed webhook body
from a week ago (e.g. replayed from a log, a backup, or a compromised
intermediary that still has the secret) was accepted exactly like a fresh
one, mark_paid included.

Fixed: app/modules/carevo_customer/controller.py's payment_webhook now
rejects (400) a validly-signed webhook whose timestamp is more than
CASHFREE_WEBHOOK_MAX_AGE_S (default 7200s / 2 hours) away from "now", in
either direction. Checked only AFTER signature verification, so an
unsigned/wrongly-signed body still gets the existing 400 for THAT reason, not
this one.

7200s, not Cashfree's suggested 300s — see the config.py comment on
CASHFREE_WEBHOOK_MAX_AGE_S: their documented retry schedule spans roughly
42 minutes, and 300s would start losing their OWN legitimate retries. Whether
x-webhook-timestamp is per-delivery-attempt or per-event is unconfirmed
against the sandbox (see docs/ops/cashfree_only_verify.sql).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import text

from app.core.config import settings
from tests.conftest import API

CF_SECRET = "whsec_replay_window_test"


def _sign(body: bytes, timestamp: str, secret: str = CF_SECRET) -> str:
    signed = f"{timestamp}{body.decode()}".encode()
    return base64.b64encode(
        hmac.new(secret.encode(), signed, hashlib.sha256).digest()
    ).decode()


def _body(order_id: str, amount: float) -> bytes:
    return json.dumps({
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"payment_status": "SUCCESS",
                       "payment_amount": amount,
                       "cf_payment_id": f"cfpay_replay_{order_id[:8]}",
                       "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
        },
    }).encode()


async def _post(client, body, timestamp, secret=CF_SECRET):
    sig = _sign(body, timestamp, secret)
    return await client.post(
        f"{API}/customer/payment/webhook", content=body,
        headers={"content-type": "application/json",
                 "x-webhook-signature": sig,
                 "x-webhook-timestamp": timestamp})


async def _unpaid_order(client, seed):
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                          json={"outlet_id": seed["outlet_id"],
                                "items": [{"menu_item_id": seed["menu_item_id"],
                                           "quantity": 1}]})
    assert r.status_code == 200, r.text
    return r.json()


class TestWebhookReplayWindow:
    async def test_seven_day_old_timestamp_is_rejected(
            self, client, db, seed, monkeypatch):
        # Order created under the stub (conftest default) — no network call
        # is ever made; only the webhook POST is gated live.
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])
        week_old = str(int(time.time()) - 7 * 24 * 3600)

        from sqlalchemy import text
        before = (await db.execute(text(
            "SELECT payment_status FROM customer_orders WHERE id = :i"),
            {"i": order["id"]})).scalar()

        r = await _post(client, body, week_old)
        assert r.status_code == 400, r.text

        after = (await db.execute(text(
            "SELECT payment_status FROM customer_orders WHERE id = :i"),
            {"i": order["id"]})).scalar()
        assert after == before, "a rejected replay must not have touched the order"

    async def test_thirty_minute_old_timestamp_is_accepted(
            self, client, seed, monkeypatch):
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])
        half_hour_old = str(int(time.time()) - 30 * 60)

        r = await _post(client, body, half_hour_old)
        assert r.status_code == 200, r.text

    async def test_default_max_age_is_7200_seconds(self):
        assert settings.CASHFREE_WEBHOOK_MAX_AGE_S == 7200

    async def test_a_future_timestamp_well_beyond_the_window_is_rejected(
            self, client, seed, monkeypatch):
        """Symmetric: the check is on the absolute difference from now, not
        only on staleness — a clock-skewed or forged future timestamp must
        not get a free pass just because it is not technically "old"."""
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])
        far_future = str(int(time.time()) + 10 * 24 * 3600)

        r = await _post(client, body, far_future)
        assert r.status_code == 400, r.text

    async def test_custom_max_age_setting_is_honoured(
            self, client, seed, monkeypatch):
        """Pins that the window is actually READ from settings, not a
        hardcoded 7200 duplicated in the controller."""
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        monkeypatch.setattr(settings, "CASHFREE_WEBHOOK_MAX_AGE_S", 60)
        body = _body(order["id"], order["total_amount"])
        ninety_seconds_old = str(int(time.time()) - 90)

        r = await _post(client, body, ninety_seconds_old)
        assert r.status_code == 400, r.text


# ==================== Task 1 (independent-verification fix) =================
# FAIL CLOSED on a malformed timestamp. LITERAL BEHAVIOUR BEFORE THIS CLASS:
# the age check lived inside `if ts_value is not None:`, so a timestamp that
# failed int() parsing (non-numeric, empty) set ts_value=None and the WHOLE
# block silently did nothing -- no 400, no log, the webhook proceeded as if
# the replay window did not exist. A validly-signed webhook with
# x-webhook-timestamp: "abc" was independently reproduced to return 200 and
# mark the order PAID. Each case here is validly signed with the EXACT
# string under test -- the attacker-can't-forge-a-signature argument does
# not apply to a genuine signer (or test) that controls what string it signs.

MALFORMED_TIMESTAMPS = ["abc", "", "-5", "1e999", "9" * 20]


class TestMalformedTimestampFailsClosed:
    @pytest.mark.parametrize("bad_ts", MALFORMED_TIMESTAMPS)
    async def test_malformed_timestamp_rejected_order_stays_pending(
            self, client, db, seed, monkeypatch, bad_ts):
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])

        r = await _post(client, body, bad_ts)
        assert r.status_code == 400, (bad_ts, r.text)

        status = await db.scalar(text(
            "SELECT payment_status FROM customer_orders WHERE id = :i"),
            {"i": order["id"]})
        assert status == "PENDING", (bad_ts, status)

    async def test_a_valid_recent_timestamp_still_passes(
            self, client, seed, monkeypatch):
        """The control: the fail-closed rewrite must not have broken the
        ordinary accepted case."""
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])
        ts = str(int(time.time()))

        r = await _post(client, body, ts)
        assert r.status_code == 200, r.text

    async def test_rejection_is_logged(self, client, seed, monkeypatch, caplog):
        import logging
        order = await _unpaid_order(client, seed)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", CF_SECRET)
        body = _body(order["id"], order["total_amount"])

        with caplog.at_level(logging.WARNING,
                             logger="app.modules.carevo_customer.controller"):
            r = await _post(client, body, "abc")
        assert r.status_code == 400
        assert any("x-webhook-timestamp" in rec.getMessage()
                  for rec in caplog.records)
