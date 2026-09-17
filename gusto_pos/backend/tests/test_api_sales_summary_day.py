"""The dine-in sales summary must mean the RESTAURANT's day, not the server's.

THE BUG THIS GUARDS
-------------------
`get_sales_summary` opened with `datetime.now().date()` and built naive LOCAL
midnight bounds, then compared them against `orders.created_at` /
`order_items.created_at` — which are `timestamp WITHOUT time zone` holding UTC
(the shared `Base.created_at` writes naive `datetime.utcnow`).

Two errors that partly hid each other, and which disagreed by deployment:

  * on Render, where the server runs UTC, the window was a true UTC
    midnight-to-midnight day — so the IST hours from 00:00 to 05:29 fell into
    the NEXT UTC day and a single night's service was split across two
    summaries;
  * on an IST developer box the bounds were IST numbers compared against UTC
    values, sliding the whole window 5h30m to 05:30 today -> 05:29 tomorrow.

Neither is the day a restaurant means by "today's sales".

WHY THESE TESTS PIN THE WINDOW AND NOT JUST "MY ORDER SHOWS UP"
---------------------------------------------------------------
"An order created now appears in today's summary" is hour-dependent: under the
OLD code on an IST box it fails at 00:35 and passes at 14:00, so as a guard it
would be asleep most of the day. The window assertions below are true at every
hour, in every server timezone — they state the invariant (the window is the
IST calendar day expressed in UTC) rather than sampling it.

The behavioural test is kept as well, because an invariant nobody exercises is
just a comment.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.modules.orders.service import _OUTLET_TZ, _utc_naive, OrderService

IST = ZoneInfo("Asia/Kolkata")


async def _legacy_order(db, outlet_id, *, created_at=None, status="paid",
                        amount=100, qty=2):
    """One dine-in Order + OrderItem, written with raw SQL.

    Raw SQL rather than the ORM so the test can place `created_at` at a chosen
    instant — the ORM default would stamp it now and the boundary cases below
    could not be expressed at all.
    """
    created = created_at if created_at is not None else datetime.utcnow()
    oid = await db.scalar(text("""
        INSERT INTO orders (id, outlet_id, table_id, total_amount, order_status,
                            source, needs_waiter_approval, created_at)
        VALUES (gen_random_uuid(), :o, 'N-1', :amt, :st, 'pos', false, :ts)
        RETURNING id"""),
        {"o": str(outlet_id), "amt": amount, "st": status, "ts": created})
    await db.execute(text("""
        INSERT INTO order_items (id, order_id, name_snap, price_snap, quantity,
                                 is_served, created_at)
        VALUES (gen_random_uuid(), :oid, 'Test Dish', :p, :q, false, :ts)"""),
        {"oid": str(oid), "p": amount, "q": qty, "ts": created})
    await db.commit()
    return oid


class TestTheWindowIsTheIstCalendarDay:
    """Hour-independent: pure arithmetic on the helper the service uses."""

    def test_the_day_starts_at_ist_midnight_expressed_in_utc(self):
        day = datetime(2026, 9, 18).date()
        start = _utc_naive(datetime.combine(day, datetime.min.time(),
                                            tzinfo=_OUTLET_TZ))
        # IST is UTC+5:30, so an IST midnight is 18:30 UTC the previous day.
        assert start == datetime(2026, 9, 17, 18, 30, 0)

    def test_the_day_is_exactly_twenty_four_hours_long(self):
        day = datetime(2026, 9, 18).date()
        start = _utc_naive(datetime.combine(day, datetime.min.time(),
                                            tzinfo=_OUTLET_TZ))
        end = _utc_naive(datetime.combine(day, datetime.max.time(),
                                          tzinfo=_OUTLET_TZ))
        assert timedelta(hours=23, minutes=59, seconds=59) < (end - start) \
            < timedelta(hours=24)

    def test_the_bounds_are_naive_because_the_columns_are(self):
        """An aware bound here would make asyncpg raise rather than compare —
        `orders.created_at` is `timestamp WITHOUT time zone`. This is the same
        edge that kept the timestamptz fix scoped to carevo_customer."""
        bound = _utc_naive(datetime.now(_OUTLET_TZ))
        assert bound.tzinfo is None

    def test_the_helper_actually_converts_rather_than_stripping(self):
        """`.replace(tzinfo=None)` alone would keep IST digits and label them
        UTC — the exact shape of the original bug, just relocated."""
        ist_noon = datetime(2026, 9, 18, 12, 0, tzinfo=IST)
        assert _utc_naive(ist_noon) == datetime(2026, 9, 18, 6, 30)


class TestTheSummaryFindsTodaysTrade:
    async def test_an_order_created_now_is_in_todays_summary(self, db, seed):
        """The behaviour, at whatever hour the suite happens to run.

        Under the old code this failed between 00:00 and 05:30 IST: `utcnow()`
        was already before the naive local-midnight lower bound, so an order
        placed moments earlier fell outside its own day.
        """
        await _legacy_order(db, seed["outlet_id"])
        summary = await OrderService.get_sales_summary(db)
        assert any(t["dish_name"] == "Test Dish" for t in summary["timeline"]), \
            "an order created seconds ago must be in today's sales summary"

    async def test_an_order_from_last_week_is_not(self, db, seed):
        """Scoping check: the window is not simply unbounded."""
        old = datetime.utcnow() - timedelta(days=7)
        await _legacy_order(db, seed["outlet_id"], created_at=old,
                            amount=999, qty=7)
        summary = await OrderService.get_sales_summary(db)
        assert all(float(t["price"]) != 999 for t in summary["timeline"]), \
            "last week's trade must not appear in today's summary"

    async def test_an_order_just_after_ist_midnight_belongs_to_the_new_day(
            self, db, seed):
        """The case that was actually broken, stated directly.

        00:30 IST is 19:00 UTC on the PREVIOUS calendar date. A window built
        from UTC dates puts this in yesterday; the restaurant considers it
        today's opening minutes. Skipped unless today's IST 00:30 is already
        past, since an order cannot be created in the future.
        """
        today_ist = datetime.now(_OUTLET_TZ).date()
        just_after_midnight = datetime.combine(
            today_ist, datetime.min.time(), tzinfo=_OUTLET_TZ) + timedelta(minutes=30)
        if just_after_midnight > datetime.now(_OUTLET_TZ):
            return  # the suite is running before 00:30 IST; nothing to assert
        await _legacy_order(db, seed["outlet_id"],
                            created_at=_utc_naive(just_after_midnight),
                            amount=777, qty=3)
        summary = await OrderService.get_sales_summary(db)
        assert any(float(t["price"]) == 777 for t in summary["timeline"]), \
            "00:30 IST is this IST day's trade, whatever the UTC date says"


class TestTheReceiptClockIsTheRestaurants:
    def test_the_bill_timestamp_is_ist_and_aware(self):
        """The receipt prints `Date: … Time: …` for someone standing in India.
        On Render, which runs UTC, a bill handed over at 20:00 IST printed
        14:30. The value is only ever strftime'd, never written to a column,
        so an aware datetime is safe here."""
        now = datetime.now(_OUTLET_TZ)
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(hours=5, minutes=30)

    def test_it_differs_from_utc_by_the_ist_offset(self):
        delta = (datetime.now(_OUTLET_TZ).replace(tzinfo=None)
                 - datetime.now(timezone.utc).replace(tzinfo=None))
        assert timedelta(hours=5, minutes=29) < delta < timedelta(hours=5, minutes=31)
