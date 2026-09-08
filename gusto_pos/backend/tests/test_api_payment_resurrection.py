"""A payment must never reopen an order the customer was told was over.

`mark_paid`'s two idempotency checks both key on the PAYMENT, never on the
order, so before the guard added here any order whose payment had not settled
could be driven to PAID whatever its status was — a late or replayed gateway
webhook could flip a CANCELLED order back to live and mint it a pickup code.
That was not hypothetical: a bulk cleanup left 98 cancelled orders in prod, each
still holding a pending gateway transaction.

The delicate part is that the guard must NOT break genuine idempotency, which is
what the gateway relies on when it retries. These tests pin both halves.
"""
import logging
import uuid

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.carevo_customer.model import CustomerOrder
from app.modules.carevo_customer.service import CarevoService

API = "/api/v1"
TERMINAL = ["CANCELLED", "COMPLETED", "ABANDONED"]


async def _orm(db, order_id):
    return (await db.execute(select(CustomerOrder).where(
        CustomerOrder.id == uuid.UUID(str(order_id))))).scalars().first()


async def _unpaid_order(client, seed):
    """A freshly created, never-paid order — status CREATED, payment PENDING."""
    r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                          json={"outlet_id": seed["outlet_id"],
                                "items": [{"menu_item_id": seed["menu_item_id"],
                                           "quantity": 1}]})
    assert r.status_code == 200, r.text
    return r.json()


async def _force_status(db, order_id, status):
    await db.execute(text(
        "UPDATE customer_orders SET status = :s WHERE id = :o"),
        {"s": status, "o": str(order_id)})
    await db.commit()


async def _row(db, order_id):
    return (await db.execute(text(
        "SELECT status, payment_status, pickup_code FROM customer_orders "
        "WHERE id = :o"), {"o": str(order_id)})).first()


@pytest.mark.asyncio
class TestTerminalOrdersCannotBeResurrected:
    @pytest.mark.parametrize("terminal", TERMINAL)
    async def test_a_late_webhook_is_refused_and_changes_nothing(
            self, client, seed, db, caplog, terminal):
        order = await _unpaid_order(client, seed)
        await _force_status(db, order["id"], terminal)

        with caplog.at_level(logging.WARNING):
            returned = await CarevoService.mark_paid(
                db, await _orm(db, order["id"]),
                gateway_payment_id="pay_late_12345", method="upi",
                raw_payload={"event": "PAYMENT_SUCCESS"})

        after = await _row(db, order["id"])
        assert after.status == terminal, "a finished order must not reopen"
        assert after.payment_status == "PENDING"
        assert after.pickup_code is None, \
            "a refused payment must not mint a pickup code"
        assert (returned.status or "").upper() == terminal

        # Loud, not silent — and carrying enough to investigate with.
        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno >= logging.WARNING]
        assert any("mark_paid REFUSED" in m for m in warnings), warnings
        blob = " ".join(warnings)
        assert str(order["id"]) in blob, "the order id must be in the warning"
        assert "pay_late_12345" in blob, \
            "the claimed payment info must be in the warning"
        assert terminal in blob

    @pytest.mark.parametrize("terminal", TERMINAL)
    async def test_no_payment_transaction_is_marked_paid(
            self, client, seed, db, terminal):
        # The order row is the visible half; the txn ledger must not claim a
        # settled payment either, or reconciliation would disagree with it.
        order = await _unpaid_order(client, seed)
        await _force_status(db, order["id"], terminal)
        await CarevoService.mark_paid(db, await _orm(db, order["id"]),
                                      gateway_payment_id="pay_x", method="upi")
        paid_txns = await db.scalar(text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE customer_order_id = :o AND status = 'PAID'"),
            {"o": order["id"]})
        assert paid_txns == 0

    async def test_the_staff_tap_is_told_no_rather_than_silently_doing_nothing(
            self, client, seed, db):
        # The webhook needs a 200 or the gateway retries forever; a human who
        # just tapped "mark paid" needs the opposite — an explicit refusal.
        order = await _unpaid_order(client, seed)
        await _force_status(db, order["id"], "CANCELLED")
        with pytest.raises(Exception) as e:
            await CarevoService.mark_order_paid_by_staff(
                db, uuid.UUID(order["id"]), uuid.UUID(str(seed["outlet_id"])))
        assert getattr(e.value, "status_code", None) == 409, e.value
        assert (await _row(db, order["id"])).status == "CANCELLED"


@pytest.mark.asyncio
class TestGenuineIdempotencyStillWorks:
    """The guard sits AFTER both idempotency returns precisely so these pass."""

    async def test_a_repeat_webhook_for_an_already_paid_order_is_unchanged(
            self, client, seed, paid_order, db):
        before = await _row(db, paid_order["id"])
        assert before.payment_status == "PAID" and before.pickup_code

        again = await CarevoService.mark_paid(
            db, await _orm(db, paid_order["id"]), method="upi")

        after = await _row(db, paid_order["id"])
        assert after.status == before.status
        assert after.payment_status == "PAID"
        assert after.pickup_code == before.pickup_code, \
            "a retry must not re-mint the code"
        assert again is not None

    async def test_a_completed_order_retry_does_not_trip_the_guard(
            self, client, seed, paid_order, db, caplog):
        # The common real case: the gateway retries after the order has already
        # been collected. COMPLETED is terminal, but payment_status is PAID, so
        # the SECOND idempotency return fires first and the guard is never
        # reached — no warning, no noise in the logs.
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        await CarevoService.verify_pickup(
            db, uuid.UUID(paid_order["id"]),
            (await _row(db, paid_order["id"])).pickup_code,
            uuid.UUID(str(seed["outlet_id"])))
        assert (await _row(db, paid_order["id"])).status == "COMPLETED"

        with caplog.at_level(logging.WARNING):
            await CarevoService.mark_paid(
                db, await _orm(db, paid_order["id"]), method="upi")

        assert (await _row(db, paid_order["id"])).status == "COMPLETED"
        assert not any("mark_paid REFUSED" in r.getMessage()
                       for r in caplog.records), \
            "an ordinary retry on a collected order must not log a warning"

    async def test_a_duplicate_gateway_payment_id_still_short_circuits(
            self, client, seed, paid_order, db):
        # The FIRST idempotency check, keyed on the payment id. Unchanged by the
        # guard, and reached before it.
        pid = await db.scalar(text(
            "SELECT gateway_payment_id FROM payment_transactions "
            "WHERE customer_order_id = :o AND status = 'PAID'"),
            {"o": paid_order["id"]})
        assert pid
        returned = await CarevoService.mark_paid(
            db, await _orm(db, paid_order["id"]), gateway_payment_id=pid)
        assert str(returned.id) == str(paid_order["id"])
        assert (await _row(db, paid_order["id"])).payment_status == "PAID"

    async def test_an_ordinary_unpaid_order_still_pays_normally(
            self, client, seed, db):
        # The guard must not touch the happy path: CREATED -> PAID, code minted.
        order = await _unpaid_order(client, seed)
        await CarevoService.mark_paid(db, await _orm(db, order["id"]),
                                      method="upi")
        after = await _row(db, order["id"])
        assert after.status == "PAID"
        assert after.payment_status == "PAID"
        assert after.pickup_code, "a real payment still mints a pickup code"
