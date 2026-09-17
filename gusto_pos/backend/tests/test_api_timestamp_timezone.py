"""A row created now must be STAMPED now — on any developer machine.

THE BUG THIS GUARDS
-------------------
The CareVo tables are all `timestamptz`, but their ORM defaults used the NAIVE
`datetime.utcnow`. SQLAlchemy's asyncpg dialect localises a naive value using
the CLIENT machine's timezone before binding it to timestamptz, so on a box
whose Postgres session runs Asia/Calcutta a "now" row was written 5h30m in the
past:

    real UTC now       2026-09-17 18:39Z
    stored created_at  2026-09-17 13:09Z      (18:39 read as IST)

Between 00:00 and 05:30 IST that shift crosses the IST date boundary, and every
day-view query -- `(created_at AT TIME ZONE 'Asia/Kolkata')::date = :day` in
active_orders and scheduled_orders -- then fails to find an order that had just
been created. It cost 22 test failures that appeared at midnight and vanished
by morning, twice read as flakiness before it was read as a clock.

WHY THE ASSERTION IS "CLOSE TO now()" AND NOT "TODAY'S IST DATE"
----------------------------------------------------------------
The date form only fails between 00:00 and 05:30 IST, so it would pass all day
and guard nothing for nineteen hours out of twenty-four. Comparing the stored
value against the DATABASE's own now() catches the 5h30m skew at ANY hour, on
any machine, in any timezone -- including on a UTC CI box, where the original
bug is invisible by construction. The invariant is simply that a row written a
moment ago is stamped a moment ago.

Both sides come from Postgres, so this never compares a Python clock to a
database clock.
"""
from datetime import datetime, timezone

from sqlalchemy import text

from app.modules.carevo_customer.model import (
    CustomerOrder, CustomerOrderItem, PaymentTransaction, _utcnow,
)

API = "/api/v1"

#: How far a freshly written timestamp may sit from the database's own now().
#: Generous on purpose -- it is not measuring latency. The failure this catches
#: is a whole timezone offset wide (the smallest real one is 15 minutes), so
#: anything under a minute cannot be a timezone and anything over it cannot be
#: a slow test.
TOLERANCE_S = 60


async def _skew(db, table: str, row_id) -> float:
    """Seconds between a row's created_at and the database's current time."""
    return await db.scalar(text(
        f"SELECT abs(extract(epoch FROM (now() - created_at))) "
        f"FROM {table} WHERE id = :i"), {"i": str(row_id)})


class TestTheDefaultIsAware:
    """Unit-level: no database, no clock, no timezone dependence.

    No asyncio mark — these are synchronous, and pytest.ini runs
    `asyncio_mode = auto`, so the async classes below need no mark either.
    """

    def test_the_shared_default_returns_an_aware_datetime(self):
        assert _utcnow().tzinfo is not None, \
            "a naive default is the bug this module exists to prevent"

    def test_it_is_actually_utc_and_not_merely_aware(self):
        assert _utcnow().utcoffset().total_seconds() == 0

    def test_it_agrees_with_the_clock(self):
        assert abs((_utcnow() - datetime.now(timezone.utc)).total_seconds()) < 5


class TestRowsAreStampedNow:
    async def test_an_order_is_stamped_at_the_moment_it_is_created(
            self, client, seed, db):
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "items": [{"menu_item_id": seed["menu_item_id"],
                                               "quantity": 1}]})
        assert r.status_code == 200, r.text
        skew = await _skew(db, "customer_orders", r.json()["id"])
        assert skew < TOLERANCE_S, (
            f"customer_orders.created_at is {skew:.0f}s from the database's own "
            f"now() — that is a timezone offset, not latency")

    async def test_the_order_items_are_too(self, client, seed, db):
        """Same default, a different table — the fix is per-column, so each
        table it covers needs its own evidence.

        The item id comes from the database, not the response: CreateOrderOut
        returns a price breakdown and a payment block, not the line items.
        """
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "items": [{"menu_item_id": seed["menu_item_id"],
                                               "quantity": 1}]})
        assert r.status_code == 200, r.text
        item_id = await db.scalar(text(
            "SELECT id FROM customer_order_items WHERE customer_order_id = :o"),
            {"o": r.json()["id"]})
        assert item_id is not None, "sanity: the order wrote a line item"
        assert await _skew(db, "customer_order_items", item_id) < TOLERANCE_S

    async def test_the_payment_transaction_is_too(self, client, seed, db, paid_order):
        txn_id = await db.scalar(text(
            "SELECT id FROM payment_transactions WHERE customer_order_id = :o "
            "ORDER BY created_at DESC LIMIT 1"), {"o": paid_order["id"]})
        assert txn_id is not None, "sanity: paying writes a transaction row"
        assert await _skew(db, "payment_transactions", txn_id) < TOLERANCE_S

    async def test_updated_at_is_stamped_now_on_a_real_transition(
            self, client, seed, db, paid_order):
        """`onupdate` carried the same naive default, and updated_at is what the
        45-minute pickup TTL measures — a sweep comparing `now()` against a
        stamp 5h30m stale would ABANDON paid orders on sight."""
        skew = await db.scalar(text(
            "SELECT abs(extract(epoch FROM (now() - updated_at))) "
            "FROM customer_orders WHERE id = :i"), {"i": paid_order["id"]})
        assert skew < TOLERANCE_S


class TestTheDayViewFindsAnOrderItJustCreated:
    """The failure as it actually presented, rather than as a stored value.

    This is the assertion that was red at 00:15 IST and green at 18:28 the same
    evening, with no code change in between.
    """

    async def test_a_new_order_is_on_todays_ist_day_view(self, client, seed, db):
        from app.modules.testing_dashboard.service import TestingService
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "items": [{"menu_item_id": seed["menu_item_id"],
                                               "quantity": 1}]})
        order_id = r.json()["id"]
        rows = await TestingService.active_orders(db, TestingService.resolve_day())
        assert any(str(o["order_id"]) == order_id for o in rows), \
            "an order created seconds ago must appear on today's IST day view"

    async def test_its_stored_ist_date_is_todays_ist_date(self, client, seed, db):
        """The same thing stated against the stored value, so a failure says
        WHICH of the two drifted."""
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "items": [{"menu_item_id": seed["menu_item_id"],
                                               "quantity": 1}]})
        row = (await db.execute(text(
            "SELECT (created_at AT TIME ZONE 'Asia/Kolkata')::date AS stored_ist, "
            "       (now()       AT TIME ZONE 'Asia/Kolkata')::date AS now_ist "
            "FROM customer_orders WHERE id = :i"), {"i": r.json()["id"]})).first()
        assert row.stored_ist == row.now_ist


class TestTheFixIsDeliberatelyNotRepoWide:
    """The guard on the other half of the diagnosis.

    asyncpg REFUSES an aware datetime bound to a `timestamp WITHOUT time zone`
    column outright (DataError: can't subtract offset-naive and offset-aware
    datetimes). So making `Base.created_at` aware would not be a smaller version
    of this fix — it would break every insert into organizations, outlets,
    menus, categories, menu_items, users, roles, orders and order_items.

    This test exists to fail in front of whoever tries to "finish the job".
    """

    def test_the_naive_column_defaults_are_still_naive(self):
        # Base is abstract and declares no table of its own, so the invariant is
        # read off concrete models that inherit its naive created_at.
        from app.modules.menu.model import MenuHistory
        from app.modules.inventory.model import Inventory
        for model, col in ((MenuHistory, "changed_at"),
                           (Inventory, "last_updated"),
                           (MenuHistory, "created_at")):   # inherited from Base
            produced = model.__table__.c[col].default.arg({})
            assert produced.tzinfo is None, (
                f"{model.__tablename__}.{col} is `timestamp WITHOUT time zone`; "
                f"asyncpg rejects an aware value for it outright. Leave it naive.")

    def test_the_carevo_defaults_are_aware(self):
        for model, col in ((CustomerOrder, "created_at"),
                           (CustomerOrder, "updated_at"),
                           (CustomerOrderItem, "created_at"),
                           (PaymentTransaction, "created_at"),
                           (PaymentTransaction, "updated_at")):
            produced = model.__table__.c[col].default.arg({})
            assert produced.tzinfo is not None, \
                f"{model.__tablename__}.{col} is timestamptz and must be aware"

    async def test_a_naive_column_table_still_accepts_writes(self, client, seed, db):
        """The consequence, proven rather than asserted: the seed fixture writes
        organizations/outlets/menus/users through the naive `Base.created_at`,
        and those inserts must keep working."""
        n = await db.scalar(text(
            "SELECT count(*) FROM outlets WHERE id = :i"), {"i": seed["outlet_id"]})
        assert n == 1
