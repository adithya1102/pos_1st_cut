"""Task 3a — mark_paid idempotency across DIFFERENT orders.

LITERAL BEHAVIOUR BEFORE THIS FILE: mark_paid's first idempotency check keyed
purely on gateway_payment_id. If that payment id was already PAID against
order A, and a later call named order B (a genuine webhook cannot name the
wrong order, but a replayed/forged one, or two orders accidentally sharing a
gateway_payment_id, could), mark_paid returned ORDER A in full — leaking its
pickup_code and status to a caller that asked about order B. Worse: the
webhook controller then ran the WHOLE paid cascade (auto_receive, outlet
push) against order A a second time, for an HTTP request that never named it.

Fixed: mark_paid now detects existing[0] != order.id, changes nothing, logs a
WARNING naming both order ids, and marks the order with a transient
`_mark_paid_cross_order_ignored` flag. The webhook controller
(carevo_customer/controller.py) checks that flag before anything else and
answers {"ok": true, "outcome": "IGNORED"} — no pickup_code, no status, from
either order.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.modules.carevo_customer.service import CarevoService
from tests.conftest import API
from tests.test_api_payment_resurrection import _orm, _row, _unpaid_order


class TestCrossOrderIdempotency:
    async def test_mark_paid_ignores_and_changes_nothing(
            self, client, seed, db, paid_order, caplog):
        # paid_order (order A) already has a PAID transaction with some
        # gateway_payment_id. order B is a second, distinct, unpaid order.
        pid = await db.scalar(text(
            "SELECT gateway_payment_id FROM payment_transactions "
            "WHERE customer_order_id = :o AND status = 'PAID'"),
            {"o": paid_order["id"]})
        assert pid

        order_b = await _unpaid_order(client, seed)
        before_b = await _row(db, order_b["id"])

        with caplog.at_level(logging.WARNING,
                              logger="app.modules.carevo_customer.service"):
            returned = await CarevoService.mark_paid(
                db, await _orm(db, order_b["id"]), gateway_payment_id=pid)

        assert getattr(returned, "_mark_paid_cross_order_ignored", False) is True

        after_b = await _row(db, order_b["id"])
        assert after_b == before_b, "order B must be completely unchanged"
        assert after_b.payment_status != "PAID"
        assert after_b.pickup_code is None

        # Order A (the real owner of the payment) is untouched too.
        row_a = await _row(db, paid_order["id"])
        assert row_a.payment_status == "PAID"

        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno == logging.WARNING]
        blob = " ".join(warnings)
        assert "IGNORED" in blob
        assert str(order_b["id"]) in blob
        assert str(paid_order["id"]) in blob

    async def test_webhook_controller_reports_ignored_with_no_leaked_data(
            self, client, seed, db, paid_order, monkeypatch):
        """End-to-end over the real route: a cashfree-shaped webhook whose
        payment id is already settled against a DIFFERENT order gets back
        IGNORED, never the other order's pickup_code or status."""
        from app.core.config import settings
        import base64
        import hashlib
        import hmac
        import json as _json
        import time

        pid = await db.scalar(text(
            "SELECT gateway_payment_id FROM payment_transactions "
            "WHERE customer_order_id = :o AND status = 'PAID'"),
            {"o": paid_order["id"]})
        assert pid

        order_b = await _unpaid_order(client, seed)

        secret = "test-secret-for-cross-order-webhook"
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "cashfree")
        monkeypatch.setattr(settings, "CASHFREE_SECRET_KEY", secret)

        body = _json.dumps({
            "type": "PAYMENT_SUCCESS_WEBHOOK",
            "data": {
                "order": {"order_id": order_b["id"]},
                "payment": {"payment_status": "SUCCESS",
                           "payment_amount": order_b["total_amount"],
                           "cf_payment_id": pid,
                           "payment_method": {"upi": {"upi_id": "cust@okaxis"}}},
            },
        })
        ts = str(int(time.time()))
        signed = f"{ts}{body}".encode()
        sig = base64.b64encode(
            hmac.new(secret.encode(), signed, hashlib.sha256).digest()
        ).decode()

        resp = await client.post(
            f"{API}/customer/payment/webhook", content=body.encode(),
            headers={"content-type": "application/json",
                     "x-webhook-timestamp": ts,
                     "x-webhook-signature": sig})
        assert resp.status_code == 200, resp.text
        body_json = resp.json()
        assert body_json.get("outcome") == "IGNORED"
        assert "pickup_code" not in body_json
        assert "status" not in body_json
