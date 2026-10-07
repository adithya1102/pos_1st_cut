"""Stock reservation (migration 033), including the concurrency proofs.

THE THREE THAT MATTER
---------------------
1. `test_fifty_concurrent_orders_for_two_units` — 50 simultaneous orders
   against 2 units. Exactly 2 may succeed, stock must land on 0, and it must
   never go negative at any point. This is the assertion the whole conditional
   -UPDATE design exists to satisfy; a read-then-write implementation
   oversells here.

2. `test_opposing_item_orders_do_not_deadlock` — carts [A,B] and [B,A] placed
   concurrently. Both must resolve. Rows are locked in ascending menu_item_id
   order precisely so a cycle cannot form; remove that sort and this hangs or
   one side dies with a deadlock-detected error.

3. `test_stock_never_goes_negative_under_mixed_quantities` — the same race
   with uneven quantities, which is where an off-by-one in the predicate
   shows up.

Note these run against the LOCAL carevo_test with a real asyncpg pool, so they
are genuine concurrency, not simulated.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.stock import COMMITTED, HELD, RELEASED
from tests.conftest import API


# ------------------------------- helpers -------------------------------------

async def _set_stock(db, item_id, qty) -> None:
    # CAST(:q AS integer) is required, not decorative. The parameter appears in
    # an IS NULL test and a > comparison, and asyncpg refuses to infer a type
    # from that ("could not determine data type of parameter $1").
    await db.execute(text("""
        UPDATE menu_items
           SET stock_remaining = CAST(:q AS integer),
               is_available = CASE
                   WHEN CAST(:q AS integer) IS NULL THEN is_available
                   WHEN CAST(:q AS integer) > 0 THEN true
                   ELSE false END
         WHERE id = :i
    """), {"q": qty, "i": str(item_id)})
    await db.commit()


async def _stock(db, item_id):
    return await db.scalar(text(
        "SELECT stock_remaining FROM menu_items WHERE id = :i"), {"i": str(item_id)})


async def _available(db, item_id) -> bool:
    return bool(await db.scalar(text(
        "SELECT is_available FROM menu_items WHERE id = :i"), {"i": str(item_id)}))


async def _reservations(db, order_id):
    rows = (await db.execute(text("""
        SELECT menu_item_id, qty, state FROM stock_reservations
         WHERE order_id = :i ORDER BY menu_item_id
    """), {"i": str(order_id)})).fetchall()
    return [(str(r.menu_item_id), r.qty, r.state) for r in rows]


async def _second_item(db, seed) -> str:
    """A second menu item on the SAME outlet's latest menu."""
    cat = await db.scalar(text("""
        SELECT c.id FROM categories c JOIN menus m ON m.id = c.menu_id
         WHERE m.outlet_id = :o ORDER BY c.created_at LIMIT 1
    """), {"o": seed["outlet_id"]})
    iid = uuid.uuid4()
    # is_veg is NOT NULL with no default, so it has to be supplied.
    await db.execute(text("""
        INSERT INTO menu_items (id, category_id, name, base_price, is_veg,
                                is_active, is_available, created_at)
        VALUES (:i, :c, :n, 50.00, true, true, true, now())
    """), {"i": str(iid), "c": cat, "n": f"TEST_CAREVO_item_{iid.hex[:6]}"})
    await db.commit()
    return str(iid)


async def _place(client, seed, items, **extra):
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"],
                             json={"outlet_id": seed["outlet_id"],
                                   "items": items, **extra})


async def _place_one(client, seed, item_id, qty=1):
    return await _place(client, seed,
                        [{"menu_item_id": item_id, "quantity": qty}])


# ============================ untracked is inert =============================

@pytest.mark.asyncio
class TestUntrackedIsInert:
    async def test_null_stock_never_blocks_and_writes_no_reservation(
            self, client, seed, db):
        """Every item today. The feature must not exist until opted into."""
        await _set_stock(db, seed["menu_item_id"], None)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=99)
        assert r.status_code == 200, r.text
        assert await _reservations(db, r.json()["id"]) == []
        assert await _stock(db, seed["menu_item_id"]) is None


# =============================== 6.1 reserve =================================

@pytest.mark.asyncio
class TestReserve:
    async def test_order_creation_decrements_and_records_a_hold(
            self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        assert r.status_code == 200, r.text

        assert await _stock(db, seed["menu_item_id"]) == 3
        res = await _reservations(db, r.json()["id"])
        assert res == [(seed["menu_item_id"], 2, HELD)]

    async def test_reserving_more_than_remains_is_409_sold_out(
            self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 1)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        assert r.status_code == 409, r.text
        d = r.json()["detail"]
        assert d["error"] == "ITEM_SOLD_OUT"
        assert d["remaining"] == 1
        assert d["requested"] == 2

    async def test_a_refused_order_is_not_created_at_all(
            self, client, seed, db):
        """Same transaction: there is no order carrying a partial hold."""
        await _set_stock(db, seed["menu_item_id"], 1)
        before = await db.scalar(text("SELECT count(*) FROM customer_orders"))
        r = await _place_one(client, seed, seed["menu_item_id"], qty=5)
        assert r.status_code == 409, r.text
        after = await db.scalar(text("SELECT count(*) FROM customer_orders"))
        assert after == before, "a rolled-back order was persisted"
        assert await _stock(db, seed["menu_item_id"]) == 1, "stock moved anyway"

    async def test_hitting_zero_hides_the_dish(self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 2)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        assert r.status_code == 200, r.text
        assert await _stock(db, seed["menu_item_id"]) == 0
        assert await _available(db, seed["menu_item_id"]) is False, (
            "a sold-out dish is still being offered")

    async def test_duplicate_lines_are_summed_not_double_reserved(
            self, client, seed, db):
        """Two lines of one dish is ONE hold of the total — the
        (order_id, menu_item_id) unique index requires it."""
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place(client, seed, [
            {"menu_item_id": seed["menu_item_id"], "quantity": 2},
            {"menu_item_id": seed["menu_item_id"], "quantity": 1},
        ])
        assert r.status_code == 200, r.text
        assert await _stock(db, seed["menu_item_id"]) == 2
        assert await _reservations(db, r.json()["id"]) == [
            (seed["menu_item_id"], 3, HELD)]

    async def test_the_cart_check_never_reserves(self, client, seed, db):
        """A cart that held stock would let any browser empty a restaurant."""
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await client.post(f"{API}/customer/cart/check",
                              headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "menu_item_ids": [seed["menu_item_id"]]})
        assert r.status_code == 200, r.text
        assert await _stock(db, seed["menu_item_id"]) == 3, "cart check reserved"


# ======================= 6.2 commit / release / sweep ========================

@pytest.mark.asyncio
class TestCommitAndRelease:
    async def _paid(self, client, seed, item_id, qty=1):
        r = await _place_one(client, seed, item_id, qty=qty)
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        p = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": oid, "method": "upi"})
        assert p.status_code == 200, p.text
        return oid

    async def test_payment_commits_the_hold(self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 5)
        oid = await self._paid(client, seed, seed["menu_item_id"], qty=2)
        assert await _reservations(db, oid) == [(seed["menu_item_id"], 2, COMMITTED)]
        assert await _stock(db, seed["menu_item_id"]) == 3, (
            "committing must not move stock again — it was taken at creation")

    async def test_reject_releases_the_units(self, client, seed, db):
        await _set_stock(db, seed["menu_item_id"], 5)
        oid = await self._paid(client, seed, seed["menu_item_id"], qty=2)
        # A paid order's hold is COMMITTED, so a reject must NOT give it back:
        # the kitchen may already have started. Verified explicitly.
        r = await client.post(f"{API}/pos/orders/{oid}/reject",
                              headers=seed["owner_auth"], json={})
        assert r.status_code == 200, r.text
        assert await _stock(db, seed["menu_item_id"]) == 3, (
            "a COMMITTED reservation was released")

    async def test_release_is_held_only_and_idempotent(self, client, seed, db):
        """Directly exercised, because every terminal path calls it blindly."""
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 5)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 3

        assert await StockService.release_for_order(db, oid, reason="t") == 1
        await db.commit()
        assert await _stock(db, seed["menu_item_id"]) == 5

        # Second call must be a no-op, not a second refund of stock.
        assert await StockService.release_for_order(db, oid, reason="t") == 0
        await db.commit()
        assert await _stock(db, seed["menu_item_id"]) == 5, "double release"

    async def test_release_from_zero_makes_the_dish_orderable_again(
            self, client, seed, db):
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 1)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=1)
        assert await _available(db, seed["menu_item_id"]) is False

        await StockService.release_for_order(db, r.json()["id"], reason="t")
        await db.commit()
        assert await _stock(db, seed["menu_item_id"]) == 1
        assert await _available(db, seed["menu_item_id"]) is True

    async def test_the_sweeper_reclaims_an_unpaid_expired_hold(
            self, client, seed, db):
        """The 45-minute pickup TTL does NOT cover unpaid orders."""
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 1

        await db.execute(text(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 minute' "
            "WHERE order_id = :i"), {"i": oid})
        await db.commit()

        assert await StockService.sweep_expired(db) >= 1
        assert await _stock(db, seed["menu_item_id"]) == 3
        assert [s for _, _, s in await _reservations(db, oid)] == [RELEASED]

    async def test_the_sweeper_leaves_paid_holds_alone(self, client, seed, db):
        """A paid order's hold is the restaurant's commitment, not a clock."""
        from app.modules.carevo_customer.stock import StockService
        await _set_stock(db, seed["menu_item_id"], 3)
        oid = await self._paid(client, seed, seed["menu_item_id"], qty=2)
        await db.execute(text(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 minute' "
            "WHERE order_id = :i"), {"i": oid})
        await db.commit()

        await StockService.sweep_expired(db)
        assert await _stock(db, seed["menu_item_id"]) == 1, (
            "a paid order's stock was reclaimed by the sweeper")

    async def test_payment_failure_keeps_the_hold_for_a_retry(
            self, client, seed, db):
        """DOCUMENTED DEVIATION: payment failure does NOT release.

        The order stays CREATED and retryable by design, so releasing would
        make the customer's own retry fail with ITEM_SOLD_OUT. The hold is
        reclaimed by the TTL sweeper instead if they never come back.
        """
        from app.modules.carevo_customer.service import CarevoService
        from app.modules.carevo_customer.model import CustomerOrder
        from sqlalchemy import select

        await _set_stock(db, seed["menu_item_id"], 3)
        r = await _place_one(client, seed, seed["menu_item_id"], qty=2)
        oid = r.json()["id"]

        order = (await db.execute(
            select(CustomerOrder).where(CustomerOrder.id == uuid.UUID(oid))
        )).scalars().first()
        await CarevoService.mark_payment_failed(db, order, method="upi")

        assert await _stock(db, seed["menu_item_id"]) == 1, (
            "the hold was released, so a retry would be told SOLD OUT")
        assert [s for _, _, s in await _reservations(db, oid)] == [HELD]


# ======================= 6.5 the concurrency proofs ==========================

@pytest.mark.asyncio
class TestConcurrencyProofs:
    async def test_fifty_concurrent_orders_for_two_units(
            self, client, seed, db):
        """THE headline proof. 50 racers, 2 units: exactly 2 win.

        A read-then-write implementation oversells here. The conditional
        UPDATE's WHERE clause is what makes it correct.
        """
        await _set_stock(db, seed["menu_item_id"], 2)

        results = await asyncio.gather(*[
            _place_one(client, seed, seed["menu_item_id"], qty=1)
            for _ in range(50)
        ], return_exceptions=True)

        ok = [r for r in results
              if not isinstance(r, Exception) and r.status_code == 200]
        sold_out = [r for r in results
                    if not isinstance(r, Exception) and r.status_code == 409]
        errors = [r for r in results if isinstance(r, Exception)]

        assert errors == [], f"unexpected exceptions: {errors[:3]}"
        assert len(ok) == 2, (
            f"{len(ok)} orders succeeded against 2 units — oversold by "
            f"{len(ok) - 2}")
        assert len(sold_out) == 48, f"{len(sold_out)} refusals, expected 48"

        remaining = await _stock(db, seed["menu_item_id"])
        assert remaining == 0, f"stock landed on {remaining}, expected 0"
        assert remaining >= 0, "stock went NEGATIVE"

        # And exactly two holds exist.
        total_held = await db.scalar(text("""
            SELECT COALESCE(sum(qty), 0) FROM stock_reservations
             WHERE menu_item_id = :i AND state = :st
        """), {"i": seed["menu_item_id"], "st": HELD})
        assert int(total_held) == 2, f"{total_held} units held, expected 2"

    async def test_stock_never_goes_negative_under_mixed_quantities(
            self, client, seed, db):
        """Uneven quantities, where an off-by-one in the predicate surfaces."""
        await _set_stock(db, seed["menu_item_id"], 10)

        results = await asyncio.gather(*[
            _place_one(client, seed, seed["menu_item_id"], qty=q)
            for q in [3, 4, 2, 5, 1, 3, 4, 2, 6, 1]
        ], return_exceptions=True)

        assert [r for r in results if isinstance(r, Exception)] == []
        remaining = await _stock(db, seed["menu_item_id"])
        assert remaining >= 0, f"stock went negative: {remaining}"

        granted = sum(
            int(r.json()["items"][0]["quantity"]) if "items" in r.json() else 0
            for r in results
            if not isinstance(r, Exception) and r.status_code == 200
        )
        held = int(await db.scalar(text("""
            SELECT COALESCE(sum(qty), 0) FROM stock_reservations
             WHERE menu_item_id = :i AND state = :st
        """), {"i": seed["menu_item_id"], "st": HELD}))
        assert held + remaining == 10, (
            f"units are not conserved: {held} held + {remaining} left != 10")
        assert granted <= 10

    async def test_opposing_item_orders_do_not_deadlock(
            self, client, seed, db):
        """Carts [A,B] and [B,A] concurrently. Both must resolve.

        Rows are locked in ascending menu_item_id order so a cycle cannot
        form. Drop that sort and this test hangs, or one side dies with
        'deadlock detected'.
        """
        a = seed["menu_item_id"]
        b = await _second_item(db, seed)
        await _set_stock(db, a, 20)
        await _set_stock(db, b, 20)

        ab = [{"menu_item_id": a, "quantity": 1},
              {"menu_item_id": b, "quantity": 1}]
        ba = [{"menu_item_id": b, "quantity": 1},
              {"menu_item_id": a, "quantity": 1}]

        results = await asyncio.wait_for(
            asyncio.gather(
                *[_place(client, seed, ab) for _ in range(6)],
                *[_place(client, seed, ba) for _ in range(6)],
                return_exceptions=True,
            ),
            timeout=60,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        assert errors == [], f"deadlock or error: {errors[:3]}"
        bad = [r.status_code for r in results if r.status_code not in (200, 409)]
        assert bad == [], f"unexpected statuses (deadlock surfaces as 500): {bad}"

        # 12 orders, 1 of each item apiece, 20 of each in stock -> all succeed.
        assert await _stock(db, a) == 8
        assert await _stock(db, b) == 8

    async def test_concurrent_orders_for_the_last_unit_of_two_items(
            self, client, seed, db):
        """Both items at 1: a cart needing both can only succeed once."""
        a = seed["menu_item_id"]
        b = await _second_item(db, seed)
        await _set_stock(db, a, 1)
        await _set_stock(db, b, 1)

        items = [{"menu_item_id": a, "quantity": 1},
                 {"menu_item_id": b, "quantity": 1}]
        results = await asyncio.gather(
            *[_place(client, seed, items) for _ in range(10)],
            return_exceptions=True)

        assert [r for r in results if isinstance(r, Exception)] == []
        ok = [r for r in results if r.status_code == 200]
        assert len(ok) == 1, f"{len(ok)} carts got the last of both items"
        assert await _stock(db, a) == 0
        assert await _stock(db, b) == 0


# ===================== 6.3 pickup-code uniqueness ============================

@pytest.mark.asyncio
class TestPickupCodeUniqueness:
    async def test_the_unique_index_exists_and_is_scoped_to_live_orders(
            self, db):
        """Codes MUST stay reusable once an order finishes — the index is
        partial for that reason, and _expire_stale_pickups depends on it."""
        defn = await db.scalar(text("""
            SELECT indexdef FROM pg_indexes
             WHERE indexname = 'customer_orders_live_pickup_code_uidx'
        """))
        assert defn is not None, "the uniqueness guard is missing"
        assert "UNIQUE" in defn
        assert "outlet_id" in defn and "pickup_code" in defn
        for terminal in ("COMPLETED", "CANCELLED", "ABANDONED"):
            assert terminal in defn, f"{terminal} not excluded — codes cannot be reused"

    async def test_a_duplicate_live_code_is_refused_by_the_database(
            self, client, seed, db):
        """The collision that used to be silent is now an error."""
        from sqlalchemy.exc import IntegrityError

        r1 = await _place_one(client, seed, seed["menu_item_id"])
        r2 = await _place_one(client, seed, seed["menu_item_id"])
        for r in (r1, r2):
            assert r.status_code == 200, r.text

        await db.execute(text(
            "UPDATE customer_orders SET pickup_code = '234567', status = 'PAID' "
            "WHERE id = :i"), {"i": r1.json()["id"]})
        await db.commit()

        with pytest.raises(IntegrityError):
            await db.execute(text(
                "UPDATE customer_orders SET pickup_code = '234567', "
                "status = 'PAID' WHERE id = :i"), {"i": r2.json()["id"]})
            await db.commit()
        await db.rollback()

    async def test_payment_still_allocates_a_code(self, client, seed, db):
        """_assign_pickup_code retries inside a SAVEPOINT, so a collision
        cannot take the payment down with it."""
        r = await _place_one(client, seed, seed["menu_item_id"])
        oid = r.json()["id"]
        p = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": oid, "method": "upi"})
        assert p.status_code == 200, p.text
        assert p.json()["pickup_code"], "no code issued"
        assert len(p.json()["pickup_code"]) == 6


# =========================== 6.4 the owner endpoint ==========================

@pytest.mark.asyncio
class TestOwnerStockEndpoint:
    async def test_set_and_clear(self, client, seed, db):
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=seed["owner_auth"], json={"quantity": 7})
        assert r.status_code == 200, r.text
        assert r.json()["stock_remaining"] == 7
        assert await _stock(db, seed["menu_item_id"]) == 7

        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=seed["owner_auth"], json={"quantity": None})
        assert r.status_code == 200, r.text
        assert r.json()["stock_remaining"] is None
        assert await _stock(db, seed["menu_item_id"]) is None

    async def test_setting_zero_hides_the_dish(self, client, seed, db):
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=seed["owner_auth"], json={"quantity": 0})
        assert r.status_code == 200, r.text
        assert r.json()["is_available"] is False

    async def test_restocking_a_sold_out_dish_brings_it_back(
            self, client, seed, db):
        """One tap, not two — otherwise a dish stays hidden with stock behind it."""
        await _set_stock(db, seed["menu_item_id"], 0)
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=seed["owner_auth"], json={"quantity": 4})
        assert r.status_code == 200, r.text
        assert r.json()["is_available"] is True
        assert await _available(db, seed["menu_item_id"]) is True

    async def test_negative_is_rejected(self, client, seed):
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=seed["owner_auth"], json={"quantity": -1})
        assert r.status_code == 422, r.text

    async def test_anonymous_is_401(self, client, seed):
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            json={"quantity": 5})
        assert r.status_code == 401, r.text

    async def test_cross_outlet_is_404(self, client, seed, db):
        """Outlet-scoped through menu_items -> categories -> menus -> outlet."""
        from app.core.auth import create_access_token
        from app.core.security import get_password_hash

        org = await db.scalar(text(
            "SELECT organization_id FROM outlets WHERE id = :o"),
            {"o": seed["outlet_id"]})
        other = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO outlets (id, location_name, city, organization_id,
                                 geofence_radius_meters, verification_status,
                                 is_visible, relocation_is_pending,
                                 is_manually_closed, created_at)
            VALUES (:i,'TEST_CAREVO_stock_other','Bengaluru',:org,500,'active',
                    true,false,false,now())
        """), {"i": str(other), "org": str(org)})
        uname = f"TEST_CAREVO_stock_{uuid.uuid4().hex[:8]}"
        await db.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active,
                               outlet_id, created_at)
            VALUES (:i,:u,:h,true,:o,now())
        """), {"i": str(uuid.uuid4()), "u": uname,
               "h": get_password_hash("x"), "o": str(other)})
        await db.commit()

        hdr = {"Authorization": f"Bearer {create_access_token(subject=uname)}"}
        r = await client.post(
            f"{API}/pos/menu-items/{seed['menu_item_id']}/stock",
            headers=hdr, json={"quantity": 99})
        assert r.status_code == 404, r.text


# ============== scheduled orders hold stock from PAYMENT (documented) ========

@pytest.mark.asyncio
class TestScheduledOrdersHoldFromPayment:
    async def test_a_scheduled_order_holds_stock_from_creation_onward(
            self, client, seed, db):
        """DOCUMENTED BEHAVIOUR, asserted so it cannot drift silently.

        A scheduled pickup reserves at CREATION like any other order and its
        hold becomes COMMITTED at PAYMENT — not at release. So a pickup booked
        for 8pm takes its units out of the day's stock the moment it is paid
        for, hours before the kitchen sees the order.

        That is the intended trade-off: the alternative is accepting money for
        an 8pm order and discovering at 7:30pm that the dish sold out, which
        is a refund rather than a 409. Restaurants tracking stock should size
        it with scheduled orders in mind.
        """
        from datetime import datetime, timedelta, timezone

        await _set_stock(db, seed["menu_item_id"], 5)
        when = datetime.now(timezone.utc) + timedelta(minutes=120)
        r = await _place(client, seed,
                         [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
                         requested_pickup_at=when.isoformat())
        assert r.status_code == 200, r.text
        oid = r.json()["id"]
        assert await _stock(db, seed["menu_item_id"]) == 3

        p = await client.post(f"{API}/customer/payment/simulate",
                              headers=seed["customer_auth"],
                              json={"order_id": oid, "method": "upi"})
        assert p.status_code == 200, p.text

        assert [s for _, _, s in await _reservations(db, oid)] == [COMMITTED], (
            "a held order's stock should be COMMITTED at payment, not at release")
        assert await _stock(db, seed["menu_item_id"]) == 3
