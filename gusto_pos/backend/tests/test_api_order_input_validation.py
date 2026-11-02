"""Task 5 — order input validation. Literal behaviour, then the two fixes.

REPORTED LITERAL BEHAVIOUR OF create_order BEFORE THIS FILE (verified by the
tests below, which pin exactly this):

  quantity 0          -> 422, rejected already (OrderItemIn.quantity: ge=1)
  quantity negative    -> 422, rejected already (ge=1)
  quantity non-integer -> 422, rejected already (pydantic int_from_float —
                           1.5 does not silently truncate to 1)
  quantity huge (1e6)  -> ACCEPTED. Nothing capped it. total_amount is
                           DECIMAL(10,2); a 1,000,000-unit line on anything
                           priced above a few rupees overflows that column
                           at commit time — an unhandled DB error, not a
                           clean 4xx.
  duplicate lines,      -> MERGED already, at the layer that actually
    same item             matters: StockService.reserve_for_order
                           (carevo_customer/stock.py ~line 72-97) explicitly
                           sums quantities for the same menu_item_id before
                           taking any hold — "two lines of the same item is
                           ONE hold of the total", enforced by the
                           (order_id, menu_item_id) unique index and pinned
                           by test_api_stock_reservation.py::TestReserve::
                           test_duplicate_lines_are_summed_not_double_reserved.
                           The order_items TABLE still gets one row per
                           submitted line (not merged into a single row), but
                           price and stock both come out correct either way,
                           since every consumer sums across lines rather than
                           assuming one row per item. An EARLIER version of
                           this file tried to REFUSE duplicates outright —
                           that broke the stock test above, which deliberately
                           exercises two lines of one item and expects 200.
                           Decision for this task: MERGED (at the stock
                           layer, pre-existing), not refused. No code change
                           was needed or made here.
  zero total after      -> REACHED (order.total_amount = max(gross-discount,
    discount               0)). The order still requires a verified payment
                           event (webhook or /payment/simulate) to reach
                           PAID — a zero-total PREPAID order is NOT
                           auto-marked paid by create_order itself. Business
                           behaviour here is UNCHANGED by this file.

FIXED (this file, schema.py only):
  - OrderItemIn.quantity gained `le=100` — a sensible upper bound. 100 is
    far above any realistic single-item restaurant order and comfortably
    below where DECIMAL(10,2) could overflow for any real menu price.
"""
from __future__ import annotations

from sqlalchemy import text

from tests.conftest import API


async def _create(client, seed, items, **extra):
    return await client.post(
        f"{API}/customer/orders", headers=seed["customer_auth"],
        json={"outlet_id": seed["outlet_id"], "items": items, **extra})


class TestQuantityBounds:
    async def test_quantity_zero_is_422(self, client, seed):
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": 0}])
        assert r.status_code == 422, r.text

    async def test_quantity_negative_is_422(self, client, seed):
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": -3}])
        assert r.status_code == 422, r.text

    async def test_quantity_non_integer_is_422(self, client, seed):
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": 1.5}])
        assert r.status_code == 422, r.text

    async def test_quantity_huge_is_now_refused(self, client, seed):
        """The fix: 1,000,000 used to be accepted outright. It is refused
        now (422) by the new le=100 bound, before any row is written."""
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"],
                            "quantity": 1_000_000}])
        assert r.status_code == 422, r.text

    async def test_quantity_at_the_new_bound_still_succeeds(self, client, seed, db):
        # Make sure the bound itself (100) is not accidentally too tight —
        # the seed item's stock is untracked (NULL) by default.
        await db.execute(text(
            "UPDATE menu_items SET stock_remaining = NULL WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        await db.commit()
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": 100}])
        assert r.status_code == 200, r.text

    async def test_quantity_just_above_the_bound_is_422(self, client, seed):
        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": 101}])
        assert r.status_code == 422, r.text


class TestDuplicateLines:
    """create_order itself still writes one order_item row per submitted
    line (not merged into one row), but the money and the stock hold both
    come out correct for duplicate lines of the same item, because the
    things that actually matter sum across lines rather than assuming a
    single row per item. No refusal: an EARLIER attempt at one broke
    test_api_stock_reservation.py's explicit, pre-existing contract that
    duplicate lines are accepted and summed into one stock hold."""

    async def test_duplicate_lines_are_accepted_and_total_is_correct(
            self, client, seed, db):
        r = await _create(client, seed, [
            {"menu_item_id": seed["menu_item_id"], "quantity": 2},
            {"menu_item_id": seed["menu_item_id"], "quantity": 3},
        ])
        assert r.status_code == 200, r.text
        # Seed item price is 100 (tests/conftest.py); 2+3 units -> 500.
        assert r.json()["total_amount"] == 500 or r.json()["final_amount"] == 500

        rows = (await db.execute(text(
            "SELECT quantity FROM customer_order_items WHERE customer_order_id = :o"),
            {"o": r.json()["id"]})).fetchall()
        assert sorted(row.quantity for row in rows) == [2, 3], (
            "two submitted lines of the same item still land as two "
            "order_item rows — this is the existing, accepted shape")

    async def test_distinct_items_are_unaffected(self, client, seed, db):
        """The control: two DIFFERENT items in one order work exactly the
        same way, each its own row, nothing summed across them."""
        import uuid as _uuid2
        new_id = str(_uuid2.uuid4())
        other_item = await db.scalar(text("""
            INSERT INTO menu_items
                (id, category_id, name, base_price, is_veg, is_active,
                 is_available, created_at)
            SELECT :nid, category_id, 'Second Item', 50, is_veg, true, true, now()
              FROM menu_items WHERE id = :i
            RETURNING id
        """), {"nid": new_id, "i": seed["menu_item_id"]})
        await db.commit()

        r = await _create(client, seed, [
            {"menu_item_id": seed["menu_item_id"], "quantity": 1},
            {"menu_item_id": str(other_item), "quantity": 1},
        ])
        assert r.status_code == 200, r.text


class TestZeroTotalAfterDiscount:
    async def test_zero_total_order_still_requires_a_verified_payment_event(
            self, client, seed, db):
        """A coupon worth MORE than the order settles total_amount at 0.
        Business behaviour under test, UNCHANGED by this file: the order is
        still created PENDING/CREATED and does NOT reach PAID until a real
        payment event (webhook or /payment/simulate) confirms it."""
        # Mint a Rs.100 points-discount coupon directly (bypassing the
        # points-threshold flow, which is not what this test is about).
        from app.modules.carevo_customer.model import Coupon
        import uuid as _uuid
        coupon_code = f"PTS-TESTCASE{_uuid.uuid4().hex[:6].upper()}"
        db.add(Coupon(
            code=coupon_code, customer_id=seed["customer_id"],
            kind=Coupon.KIND_POINTS_DISCOUNT, discount_amount=100.0,
            status="ACTIVE",
        ))
        await db.commit()

        # An item priced at or below Rs.100 so the coupon fully covers it.
        price = await db.scalar(text(
            "SELECT base_price FROM menu_items WHERE id = :i"),
            {"i": seed["menu_item_id"]})
        assert float(price) <= 100.0, \
            "seed menu item must be <= Rs.100 for this test to reach total=0"

        r = await _create(client, seed,
                          [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
                          coupon_code=coupon_code)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["final_amount"] == 0 or body["total_amount"] == 0, body

        row = (await db.execute(text(
            "SELECT status, payment_status FROM customer_orders WHERE id = :i"),
            {"i": body["id"]})).first()
        assert row.payment_status != "PAID", \
            "a zero-total order must not be auto-marked PAID by create_order"
        assert row.status in ("CREATED",), row.status

        # It CAN still be paid — via the ordinary verified-event path, same
        # as any other order. Confirms the zero total does not somehow make
        # the order un-payable either.
        pay = await client.post(f"{API}/customer/payment/simulate",
                                headers=seed["customer_auth"],
                                json={"order_id": body["id"], "method": "upi"})
        assert pay.status_code == 200, pay.text
        after = (await db.execute(text(
            "SELECT payment_status FROM customer_orders WHERE id = :i"),
            {"i": body["id"]})).scalar()
        assert after == "PAID"
