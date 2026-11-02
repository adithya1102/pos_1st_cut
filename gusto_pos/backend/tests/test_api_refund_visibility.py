"""Task 1 — refund visibility (backend halves: 1b and 1c).

LITERAL BEHAVIOUR BEFORE THIS FILE:

  (b) mark_paid set refund_required=true in two branches — the terminal-order
      branch and the stock-gone-after-payment branch (carevo_customer/
      service.py) — with only a WARNING log and no stable marker a human or
      an alert rule could grep for. Neither branch logged the amount, so
      there was no way to answer "how much money is sitting in the
      refund-due queue right now" from the logs alone.

  (c) In the stock-gone branch, the order's pickup_code survived the
      cancellation — it was minted earlier in mark_paid, before the stock
      re-reserve was attempted, and nothing cleared it afterwards. A
      CANCELLED order with refund_required=true could still be presented at
      the counter with what looked like a valid pickup code.

Both are fixed in CarevoService.mark_paid. This file proves each with a test
that fails without the fix: the ERROR line is asserted by its stable marker
REFUND_REQUIRED_FLAGGED, and the pickup_code assertion is a plain DB read on
the cancelled row.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from tests.conftest import API
from tests.test_api_stock_hold_ttl import _force_expired, _order_row, _pay
from tests.test_api_stock_reservation import _customers, _place_one, _set_stock, _stock
from tests.test_api_payment_resurrection import _force_status, _orm, _row, _unpaid_order
from app.modules.carevo_customer.service import CarevoService


async def _pickup_code(db, order_id):
    return await db.scalar(text(
        "SELECT pickup_code FROM customer_orders WHERE id = :i"),
        {"i": str(order_id)})


# ===================== (b) REFUND_REQUIRED_FLAGGED — terminal order ==========

class TestRefundFlaggedLogTerminalOrder:
    async def test_error_log_line_on_late_payment_after_expiry(
            self, client, seed, db, caplog):
        order = await _unpaid_order(client, seed)
        await _force_status(db, order["id"], "CANCELLED")

        with caplog.at_level(logging.WARNING,
                              logger="app.modules.carevo_customer.service"):
            await CarevoService.mark_paid(
                db, await _orm(db, order["id"]),
                gateway_payment_id="pay_late_flag_1", method="upi",
                amount_paise=20000,
                raw_payload={"event": "PAYMENT_SUCCESS"})

        after = await _row(db, order["id"])
        assert after.status == "CANCELLED"

        flagged = [rec for rec in caplog.records
                   if "REFUND_REQUIRED_FLAGGED" in rec.getMessage()
                   and rec.levelno == logging.ERROR]
        assert flagged, "no ERROR-level REFUND_REQUIRED_FLAGGED line emitted"
        msg = flagged[0].getMessage()
        assert str(order["id"]) in msg
        assert str(seed["outlet_id"]) in msg
        assert "20000" in msg
        assert "late_payment_after_expiry" in msg

    async def test_no_duplicate_log_line_on_a_repeat_late_webhook(
            self, client, seed, db, caplog):
        """The UPDATE is WHERE NOT refund_required, so a second late webhook
        for the same already-flagged order must not log a second ERROR line —
        there is nothing new to tell anyone."""
        order = await _unpaid_order(client, seed)
        await _force_status(db, order["id"], "CANCELLED")

        await CarevoService.mark_paid(
            db, await _orm(db, order["id"]),
            gateway_payment_id="pay_late_flag_2", method="upi",
            raw_payload={"event": "PAYMENT_SUCCESS"})

        caplog.clear()
        with caplog.at_level(logging.WARNING,
                              logger="app.modules.carevo_customer.service"):
            await CarevoService.mark_paid(
                db, await _orm(db, order["id"]),
                gateway_payment_id="pay_late_flag_3", method="upi",
                raw_payload={"event": "PAYMENT_SUCCESS"})

        flagged = [rec for rec in caplog.records
                   if "REFUND_REQUIRED_FLAGGED" in rec.getMessage()]
        assert not flagged, "re-flagged an order that was already flagged"


# ===================== (b) REFUND_REQUIRED_FLAGGED — stock-gone ===============

class TestRefundFlaggedLogStockGone:
    async def test_error_log_line_on_stock_gone_after_payment(
            self, client, seed, db, caplog):
        await _set_stock(db, seed["menu_item_id"], 2)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        from app.modules.carevo_customer.stock import StockService
        assert await StockService.sweep_expired(db) >= 1
        other = (await _customers(db, 1))[0]
        taken = await _place_one(client, seed, seed["menu_item_id"], qty=2,
                                 auth=other)
        assert taken.status_code == 200, taken.text

        with caplog.at_level(logging.ERROR,
                              logger="app.modules.carevo_customer.service"):
            pay = await _pay(client, seed, oid)
        assert pay.status_code == 200, pay.text

        row = await _order_row(db, oid)
        assert row.status == "CANCELLED"
        assert row.refund_required is True

        flagged = [rec for rec in caplog.records
                   if "REFUND_REQUIRED_FLAGGED" in rec.getMessage()
                   and rec.levelno == logging.ERROR]
        assert flagged, "no ERROR-level REFUND_REQUIRED_FLAGGED line emitted"
        msg = flagged[0].getMessage()
        assert str(oid) in msg
        assert str(seed["outlet_id"]) in msg
        assert "stock_gone_after_payment" in msg
        # No customer contact details anywhere in the line (phone number).
        assert seed.get("customer_phone", "__none__") not in msg


# ===================== (c) pickup_code cleared on stock-gone cancel ===========

class TestPickupCodeClearedOnStockGoneCancel:
    async def test_cancelled_row_has_no_pickup_code_and_refund_required(
            self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 2)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        await _force_expired(db, oid)

        from app.modules.carevo_customer.stock import StockService
        assert await StockService.sweep_expired(db) >= 1
        other = (await _customers(db, 1))[0]
        taken = await _place_one(client, seed, seed["menu_item_id"], qty=2,
                                 auth=other)
        assert taken.status_code == 200, taken.text

        pay = await _pay(client, seed, oid)
        assert pay.status_code == 200, pay.text

        row = await _order_row(db, oid)
        assert row.status == "CANCELLED"
        assert row.payment_status == "PAID", \
            "payment_status must stay the truth that money was received"
        assert row.refund_required is True

        code = await _pickup_code(db, oid)
        assert code is None, \
            "a cancelled, refund-due order must not keep a presentable pickup code"

        # The API response itself must not hand out a code either.
        assert pay.json().get("pickup_code") in (None, ""), pay.text
