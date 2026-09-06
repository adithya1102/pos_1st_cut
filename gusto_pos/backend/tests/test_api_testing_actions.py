"""Testing-dashboard manual Approve / Reject + the IST placed-at column.

Approve and Reject reuse the EXACT staff service functions — advance_status and
CarevoService.reject_order — so this asserts the real effects (RECEIVED on
approve, CANCELLED on reject) and that the server-computed can_approve/can_reject
flags gate the buttons to the states the real endpoints actually accept.
"""
import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_customer.service import CarevoService
from app.modules.testing_dashboard.service import TestingService

API = "/api/v1"
KEY = "test-dash-key"
HDR = {"X-Testing-Key": KEY}
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _configure_key():
    prev = settings.TESTING_DASHBOARD_KEY
    settings.TESTING_DASHBOARD_KEY = KEY
    yield
    settings.TESTING_DASHBOARD_KEY = prev


async def _orders(client, day: str | None = None):
    url = f"{API}/testing/orders" + (f"?day={day}" if day else "")
    r = await client.get(url, headers=HDR)
    assert r.status_code == 200, r.text
    return r.json()


async def _row(client, order_id):
    return next((o for o in await _orders(client)
                 if str(o["order_id"]) == order_id), None)


async def _db_status(db, order_id):
    return await db.scalar(text(
        "SELECT status FROM customer_orders WHERE id = :o"), {"o": order_id})


# ------------------------------ Task 2: date/time -------------------------
@pytest.mark.asyncio
class TestPlacedAtIST:
    async def test_created_at_ist_is_present_and_correctly_formatted(
            self, client, seed, paid_order, db):
        row = await _row(client, paid_order["id"])
        assert row is not None
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", row["created_at_ist"]), \
            row["created_at_ist"]
        # Exactly the DB timestamp converted to Asia/Kolkata.
        created = await db.scalar(text(
            "SELECT created_at FROM customer_orders WHERE id = :o"),
            {"o": paid_order["id"]})
        assert row["created_at_ist"] == created.astimezone(IST).strftime("%Y-%m-%d %H:%M")


# ---------------------- Task 3: action-flag gating ------------------------
@pytest.mark.asyncio
class TestActionFlags:
    async def test_paid_order_can_be_approved_and_rejected(
            self, client, seed, paid_order):
        row = await _row(client, paid_order["id"])
        assert row["status"] == "PAID"
        assert row["can_approve"] is True
        assert row["can_reject"] is True

    async def test_preparing_hides_approve_keeps_reject(
            self, client, seed, paid_order, db):
        # PREPARING is in the kitchen: no Approve, but Reject still valid (matches
        # owner_app's _rejectable and the server's REJECTABLE_STATUSES).
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="PREPARING")
        row = await _row(client, paid_order["id"])
        assert row["status"] == "PREPARING"
        assert row["can_approve"] is False
        assert row["can_reject"] is True

    async def test_ready_hides_both(self, client, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        row = await _row(client, paid_order["id"])
        assert row["status"] == "READY"
        assert row["can_approve"] is False
        assert row["can_reject"] is False


# ------------------- an unpaid order is not approvable --------------------
@pytest.mark.asyncio
class TestCreatedIsNotApprovable:
    """CREATED was removed from _APPROVABLE_STATUSES.

    advance_status maps CREATED straight to RECEIVED, so Approve on an unpaid
    order put it in the kitchen queue indistinguishable from a paid one — it
    would then be cooked and handed over for free.
    """

    async def _created_order(self, client, seed):
        r = await client.post(f"{API}/customer/orders",
                              headers=seed["customer_auth"],
                              json={"outlet_id": seed["outlet_id"],
                                    "items": [{"menu_item_id": seed["menu_item_id"],
                                               "quantity": 1}]})
        assert r.status_code == 200, r.text
        return r.json()

    async def test_can_approve_is_false_for_created(self, client, seed, db):
        order = await self._created_order(client, seed)
        row = await _row(client, order["id"])
        assert row is not None and row["status"] == "CREATED"
        assert row["payment_status"] == "PENDING"
        assert row["can_approve"] is False, \
            "an unpaid order must not offer Approve"
        # Nor anything else — nothing can be done with it but Reject, which the
        # real reject_order refuses for CREATED anyway.
        assert row["can_ready"] is False
        assert row["can_deliver"] is False

    async def test_the_endpoint_refuses_a_created_order_too(
            self, client, seed, db):
        # Hiding the button is not the gate: advance_status would still map
        # CREATED -> RECEIVED for anyone calling the route directly.
        order = await self._created_order(client, seed)
        r = await client.post(
            f"{API}/testing/orders/{order['id']}/approve", headers=HDR)
        assert r.status_code == 409, r.text
        assert await _db_status(db, order["id"]) == "CREATED", \
            "a refused Approve must leave the unpaid order where it was"


# --------------------------- Task 3: approve ------------------------------
@pytest.mark.asyncio
class TestApprove:
    async def test_approve_advances_paid_to_received(
            self, client, seed, paid_order, db):
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/approve", headers=HDR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_status"] == "PAID"
        assert body["status"] == "RECEIVED"
        assert await _db_status(db, paid_order["id"]) == "RECEIVED"

    async def test_approve_received_advances_to_preparing(
            self, client, seed, paid_order, db):
        await client.post(f"{API}/testing/orders/{paid_order['id']}/approve",
                          headers=HDR)  # PAID -> RECEIVED
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/approve", headers=HDR)
        assert r.json()["status"] == "PREPARING"
        assert await _db_status(db, paid_order["id"]) == "PREPARING"

    async def test_approve_unknown_order_404(self, client, seed):
        r = await client.post(
            f"{API}/testing/orders/{uuid.uuid4()}/approve", headers=HDR)
        assert r.status_code == 404


# --------------------------- Task 3: reject -------------------------------
@pytest.mark.asyncio
class TestReject:
    async def test_reject_cancels_order_and_records_event(
            self, client, seed, paid_order, db):
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/reject", headers=HDR,
            json={"reason": "test reject"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "CANCELLED"
        assert await _db_status(db, paid_order["id"]) == "CANCELLED"
        # It went through the real reject_order: an ORDER_REJECTED event exists.
        ev = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id = :o "
            "AND event_type = 'ORDER_REJECTED'"), {"o": paid_order["id"]})
        assert ev == 1

    async def test_rejected_order_stays_on_the_day_as_a_cancelled_record(
            self, client, seed, paid_order):
        # CHANGED: it used to be filtered out of the view entirely. The list is
        # a DAY view now, so a cancelled order stays as the record of what
        # happened — it just offers no actions.
        await client.post(f"{API}/testing/orders/{paid_order['id']}/reject",
                          headers=HDR, json={"reason": "gone"})
        row = await _row(client, paid_order["id"])
        assert row is not None, "a cancelled order must not vanish from its day"
        assert row["status"] == "CANCELLED"
        assert not any((row["can_approve"], row["can_ready"],
                        row["can_deliver"], row["can_reject"]))

    async def test_reject_on_ready_is_refused_by_the_real_endpoint(
            self, client, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/reject", headers=HDR,
            json={"reason": "too late"})
        assert r.status_code == 409, r.text
        assert await _db_status(db, paid_order["id"]) == "READY"  # unchanged


# ---------------------------- manual Ready --------------------------------
# Ready is the manual twin of the auto-advance worker's final stage: the SAME
# CarevoService.advance_status, given target="READY". Reaching READY is what
# fires the pre-existing auto-pickup hook, so these assert that the hook behaves
# identically on this second path — roster completes, non-roster stops — rather
# than re-testing the hook itself.
async def _to_preparing(db, order_id):
    await CarevoService.advance_status(db, uuid.UUID(order_id), target="PREPARING")


async def _put_on_roster(db, seed):
    phone = await db.scalar(text(
        "SELECT phone_number FROM customers WHERE id = :c"),
        {"c": seed["customer_id"]})
    await TestingService.add_tester(db, phone, "Tester")
    return phone


async def _pickup_verified(db, order_id) -> bool:
    ev = await db.scalar(text(
        "SELECT count(*) FROM order_events WHERE order_id = :o "
        "AND event_type = 'PICKUP_VERIFIED'"), {"o": order_id})
    vat = await db.scalar(text(
        "SELECT pickup_verified_at FROM customer_orders WHERE id = :o"),
        {"o": order_id})
    return ev == 1 and vat is not None


async def _db_pickup_code(db, order_id):
    return await db.scalar(text(
        "SELECT pickup_code FROM customer_orders WHERE id = :o"), {"o": order_id})


@pytest.mark.asyncio
class TestReadyFlag:
    async def test_can_ready_only_at_preparing(self, client, seed, paid_order, db):
        # PAID: not yet in the kitchen.
        assert (await _row(client, paid_order["id"]))["can_ready"] is False

        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="RECEIVED")
        assert (await _row(client, paid_order["id"]))["can_ready"] is False

        await _to_preparing(db, paid_order["id"])
        row = await _row(client, paid_order["id"])
        assert row["can_ready"] is True
        # And it never doubles up with Approve — Approve stops before PREPARING.
        assert row["can_approve"] is False

        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        assert (await _row(client, paid_order["id"]))["can_ready"] is False


@pytest.mark.asyncio
class TestReadyAction:
    async def test_ready_advances_preparing_to_ready(
            self, client, seed, paid_order, db):
        await _to_preparing(db, paid_order["id"])
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/ready", headers=HDR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["previous_status"] == "PREPARING"
        assert body["status"] == "READY"
        assert await _db_status(db, paid_order["id"]) == "READY"

    async def test_non_roster_order_stops_at_ready(
            self, client, seed, paid_order, db):
        # Nobody on the roster: the auto-pickup hook gates itself off, so READY
        # is the end of the line — exactly as on the automatic path.
        await _to_preparing(db, paid_order["id"])
        await client.post(f"{API}/testing/orders/{paid_order['id']}/ready",
                          headers=HDR)
        assert await _db_status(db, paid_order["id"]) == "READY"
        assert not await _pickup_verified(db, paid_order["id"]), \
            "a non-roster order must never be auto-picked-up"
        # Still live, so a tester can read the code off the row.
        assert (await _row(client, paid_order["id"]))["status"] == "READY"

    async def test_roster_order_still_auto_picks_up_through_this_path(
            self, client, seed, paid_order, db):
        # The regression this guards: auto-pickup lives inside advance_status and
        # fires on reaching READY, so it must trigger identically whether READY
        # came from the poller or from this button.
        await _put_on_roster(db, seed)
        await _to_preparing(db, paid_order["id"])

        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/ready", headers=HDR)
        assert r.status_code == 200, r.text
        # The response reports what actually happened — the hook ran inline.
        assert r.json()["status"] == "COMPLETED"
        assert await _db_status(db, paid_order["id"]) == "COMPLETED"
        assert await _pickup_verified(db, paid_order["id"]), \
            "must complete via the real verify_pickup path, not a shortcut"

    async def test_stale_button_cannot_skip_stages(
            self, client, seed, paid_order, db):
        # advance_status with an explicit target does NOT check the current
        # status, so without the gate in ready_order a PAID order would jump
        # straight past the kitchen to READY.
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/ready", headers=HDR)
        assert r.status_code == 409, r.text
        assert await _db_status(db, paid_order["id"]) == "PAID"  # unchanged

    async def test_ready_unknown_order_404(self, client, seed):
        r = await client.post(
            f"{API}/testing/orders/{uuid.uuid4()}/ready", headers=HDR)
        assert r.status_code == 404


@pytest.mark.asyncio
class TestReadyLeavesTheOtpAlone:
    async def test_pickup_code_is_identical_before_and_after(
            self, client, seed, paid_order, db):
        """OTP visibility is explicitly out of scope for this change.

        Asserted as an EQUALITY against the value captured beforehand, not as
        'the field is still present' — a regression that regenerated or blanked
        the code would pass the weaker check.
        """
        await _to_preparing(db, paid_order["id"])
        before_row = await _row(client, paid_order["id"])
        before_api = before_row["pickup_code"]
        before_db = await _db_pickup_code(db, paid_order["id"])
        assert before_api, "fixture precondition: a paid order has a code"

        await client.post(f"{API}/testing/orders/{paid_order['id']}/ready",
                          headers=HDR)

        after_row = await _row(client, paid_order["id"])
        assert after_row["pickup_code"] == before_api
        assert await _db_pickup_code(db, paid_order["id"]) == before_db


# ------------------ flat list, newest-first, day filter --------------------
# The page no longer groups by restaurant, so the ORDER the endpoint returns is
# the order the operator reads top-to-bottom. That makes the sort part of the
# contract rather than a detail the client could re-derive.
async def _second_outlet(db) -> tuple[str, str]:
    """Another outlet in the same world, so cross-restaurant ordering can be
    asserted — the seed fixture builds exactly one."""
    oid, org = str(uuid.uuid4()), await db.scalar(text(
        "SELECT id FROM organizations ORDER BY created_at DESC LIMIT 1"))
    name = f"Second Kitchen {oid[:6]}"
    await db.execute(text("""
        INSERT INTO outlets (id, organization_id, location_name, city, is_visible,
                             upi_id, geofence_radius_meters, verification_status,
                             created_at)
        VALUES (:i,:o,:n,'Testville', true, 'test@upi', 150, 'active', now())"""),
        {"i": oid, "o": str(org), "n": name})
    await db.commit()
    return oid, name


_AUTO_CODE = object()  # sentinel: generate one. Explicit None means "no code".


async def _insert_order(db, seed, *, outlet_id, created_at, status="PAID",
                        code=_AUTO_CODE):
    """A customer_order written straight to the table.

    The dashboard list is a raw SELECT, so a directly-inserted row is exactly
    what it would read in production — and it is the only way to pin created_at
    to a chosen day, which is the thing under test.
    """
    oid = str(uuid.uuid4())
    # ux_customer_orders_pickup_live makes a code unique among an outlet's live
    # orders, so every inserted row needs its own.
    if code is _AUTO_CODE:
        code = f"{uuid.uuid4().int % 1000000:06d}"
    # failed_attempts / is_locked are NOT NULL with no server default — the ORM
    # normally fills them in Python, so a raw INSERT must supply them. Same
    # wrinkle the seed fixture documents for outlets.
    await db.execute(text("""
        INSERT INTO customer_orders (id, customer_id, outlet_id, status,
                                     payment_status, total_amount, discount_amount,
                                     pickup_code, failed_attempts, is_locked,
                                     created_at, updated_at)
        VALUES (:i,:c,:o,:s,'PAID', 100, 0, :p, 0, false, :t, now())"""),
        {"i": oid, "c": str(seed["customer_id"]), "o": str(outlet_id),
         "s": status, "p": code, "t": created_at})
    await db.commit()
    return oid


@pytest.mark.asyncio
class TestFlatListAndDayFilter:
    async def test_orders_from_all_outlets_are_one_flat_newest_first_list(
            self, client, seed, db):
        other_id, other_name = await _second_outlet(db)
        today = datetime.now(IST).date()
        base = datetime(today.year, today.month, today.day, 9, 0, tzinfo=IST)

        oldest = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"], created_at=base)
        middle = await _insert_order(
            db, seed, outlet_id=other_id, created_at=base + timedelta(hours=1))
        newest = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=base + timedelta(hours=2))

        rows = await _orders(client, str(today))
        ids = [str(o["order_id"]) for o in rows]
        # Interleaved by TIME, not clustered by restaurant — the whole point of
        # flattening. The middle order belongs to the other outlet and must sit
        # between two orders of the first one.
        assert ids.index(newest) < ids.index(middle) < ids.index(oldest)

        # Strictly descending across the entire list, whoever the outlet is.
        stamps = [o["created_at"] for o in rows]
        assert stamps == sorted(stamps, reverse=True)

        # The restaurant is still on every row — it became a column, not a
        # heading, so nothing was lost by removing the grouping.
        assert all("outlet_name" in o for o in rows)
        assert next(o for o in rows if str(o["order_id"]) == middle)[
            "outlet_name"] == other_name

    async def test_day_filter_returns_only_that_day(self, client, seed, db):
        today = datetime.now(IST).date()
        yesterday = today - timedelta(days=1)
        t_id = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime(today.year, today.month, today.day, 10, tzinfo=IST))
        y_id = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime(yesterday.year, yesterday.month, yesterday.day,
                                10, tzinfo=IST))

        today_ids = {str(o["order_id"]) for o in await _orders(client, str(today))}
        assert t_id in today_ids
        assert y_id not in today_ids, "yesterday's order must not show under today"

        y_ids = {str(o["order_id"]) for o in await _orders(client, str(yesterday))}
        assert y_id in y_ids
        assert t_id not in y_ids

    async def test_default_day_is_today_in_ist(self, client, seed, db):
        # No day param at all == the IST calendar date, which is what the page
        # preselects. Asserted through the endpoint, not just the helper.
        today = datetime.now(IST).date()
        mine = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime(today.year, today.month, today.day, 10, tzinfo=IST))
        assert TestingService.resolve_day() == str(today)
        assert mine in {str(o["order_id"]) for o in await _orders(client)}

    async def test_a_malformed_day_is_refused_not_guessed(self, client, seed):
        r = await client.get(f"{API}/testing/orders?day=not-a-date", headers=HDR)
        assert r.status_code == 422, r.text


# --------------------- a day is the whole day, finished or not -------------
# The view used to exclude COMPLETED/CANCELLED/ABANDONED, so a past day showed
# only what was somehow still live from it — which, past the 45-minute pickup
# TTL, is nothing. An order swept to ABANDONED simply disappeared from the one
# surface being watched. A day now shows everything that happened on it.
@pytest.mark.asyncio
class TestDayShowsFullHistory:
    async def test_a_past_day_returns_finished_and_live_orders_alike(
            self, client, seed, db):
        past = datetime.now(IST).date() - timedelta(days=3)
        at = lambda h: datetime(past.year, past.month, past.day, h, tzinfo=IST)

        made = {
            "COMPLETED": await _insert_order(
                db, seed, outlet_id=seed["outlet_id"], created_at=at(9),
                status="COMPLETED"),
            "ABANDONED": await _insert_order(
                db, seed, outlet_id=seed["outlet_id"], created_at=at(10),
                status="ABANDONED"),
            "CANCELLED": await _insert_order(
                db, seed, outlet_id=seed["outlet_id"], created_at=at(11),
                status="CANCELLED"),
            "PREPARING": await _insert_order(
                db, seed, outlet_id=seed["outlet_id"], created_at=at(12),
                status="PREPARING"),
        }

        rows = {str(o["order_id"]): o for o in await _orders(client, str(past))}
        for status, oid in made.items():
            assert oid in rows, f"{status} order missing from its own day"
            assert rows[oid]["status"] == status

        # Still newest-first across the mixed set — the sort did not become
        # status-aware.
        returned = [str(o["order_id"]) for o in await _orders(client, str(past))
                    if str(o["order_id"]) in made.values()]
        assert returned == [made["PREPARING"], made["CANCELLED"],
                            made["ABANDONED"], made["COMPLETED"]]

    async def test_today_shows_finished_orders_too(self, client, seed, db):
        # No regression to "today = live only": the rule is the same on every
        # day, which is the point of removing the filter rather than special-
        # casing past days.
        today = datetime.now(IST).date()
        done = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime(today.year, today.month, today.day, 8, tzinfo=IST),
            status="COMPLETED")
        live = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime(today.year, today.month, today.day, 9, tzinfo=IST))

        ids = {str(o["order_id"]) for o in await _orders(client)}  # default day
        assert done in ids and live in ids

    async def test_terminal_rows_offer_no_actions(self, client, seed, db):
        # The buttons need no new gate: every can_* set is built from statuses
        # that contain no terminal one, so a finished row offers nothing on its
        # own. Asserted rather than assumed, since finished rows are now visible
        # and a regression here would put a live button on a dead order.
        today = datetime.now(IST).date()
        for status in ("COMPLETED", "CANCELLED", "ABANDONED"):
            oid = await _insert_order(
                db, seed, outlet_id=seed["outlet_id"],
                created_at=datetime(today.year, today.month, today.day, 8,
                                    tzinfo=IST),
                status=status)
            row = await _row(client, oid)
            assert row is not None and row["status"] == status
            assert (row["can_approve"], row["can_ready"], row["can_deliver"],
                    row["can_reject"]) == (False, False, False, False), \
                f"{status} must offer no actions"

    async def test_a_day_with_nothing_on_it_is_empty_not_an_error(
            self, client, seed):
        long_ago = datetime.now(IST).date() - timedelta(days=400)
        assert await _orders(client, str(long_ago)) == []


# ---------------------------- manual Delivered -----------------------------
# Delivered calls CarevoService.verify_pickup with the order's OWN pickup_code —
# the same call maybe_auto_pickup and the owner_app counter scan make. So these
# assert the real effects of a verification, not a status write.
@pytest.mark.asyncio
class TestDeliverFlag:
    async def test_can_deliver_matches_verify_pickups_own_live_set(
            self, client, seed, paid_order, db):
        # verify_pickup accepts `status in _LIVE_STATUSES`; the flag must offer
        # itself over exactly that set and nothing wider.
        for target in (None, "RECEIVED", "PREPARING", "READY"):
            if target:
                await CarevoService.advance_status(
                    db, uuid.UUID(paid_order["id"]), target=target)
            row = await _row(client, paid_order["id"])
            assert row["can_deliver"] is True, f"{row['status']} is a live status"

    async def test_can_deliver_false_without_a_pickup_code(
            self, client, seed, db):
        # Live but codeless: verify_pickup compares against order.pickup_code,
        # so it could never succeed and the button must not be offered.
        oid = await _insert_order(
            db, seed, outlet_id=seed["outlet_id"],
            created_at=datetime.now(IST), code=None)
        row = await _row(client, oid)
        assert row["status"] == "PAID" and row["pickup_code"] is None
        assert row["can_deliver"] is False


@pytest.mark.asyncio
class TestDeliverAction:
    async def test_deliver_completes_the_order_via_verify_pickup(
            self, client, seed, paid_order, db):
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/deliver", headers=HDR)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verified"] is True
        assert body["previous_status"] == "PAID"
        assert body["status"] == "COMPLETED"
        assert await _db_status(db, paid_order["id"]) == "COMPLETED"

        # It went through the REAL verification, not a status assignment: the
        # event and the timestamp only exist on that path.
        ev = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id = :o "
            "AND event_type = 'PICKUP_VERIFIED'"), {"o": paid_order["id"]})
        assert ev == 1
        assert await db.scalar(text(
            "SELECT pickup_verified_at FROM customer_orders WHERE id = :o"),
            {"o": paid_order["id"]}) is not None

    async def test_delivered_order_stays_on_the_day_as_a_completed_record(
            self, client, seed, paid_order):
        # CHANGED alongside Reject: a handed-over order stays on its day,
        # marked COMPLETED and offering nothing. Same treatment, no special case.
        await client.post(f"{API}/testing/orders/{paid_order['id']}/deliver",
                          headers=HDR)
        row = await _row(client, paid_order["id"])
        assert row is not None, "a completed order must not vanish from its day"
        assert row["status"] == "COMPLETED"
        assert not any((row["can_approve"], row["can_ready"],
                        row["can_deliver"], row["can_reject"]))

    async def test_deliver_from_ready_works_too(self, client, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/deliver", headers=HDR)
        assert r.json()["status"] == "COMPLETED"

    async def test_a_stale_button_cannot_burn_the_orders_attempt_budget(
            self, client, seed, paid_order, db):
        # The reason the gate is server-side: verify_pickup counts a non-live
        # status as a FAILED ATTEMPT and locks the order on the third. A refused
        # request must leave failed_attempts untouched.
        await client.post(f"{API}/testing/orders/{paid_order['id']}/deliver",
                          headers=HDR)          # -> COMPLETED
        r = await client.post(
            f"{API}/testing/orders/{paid_order['id']}/deliver", headers=HDR)
        assert r.status_code == 409, r.text
        row = (await db.execute(text(
            "SELECT failed_attempts, is_locked FROM customer_orders WHERE id = :o"),
            {"o": paid_order["id"]})).first()
        assert row.failed_attempts == 0, "a refused Deliver must cost no attempt"
        assert row.is_locked is False

    async def test_deliver_unknown_order_404(self, client, seed):
        r = await client.post(
            f"{API}/testing/orders/{uuid.uuid4()}/deliver", headers=HDR)
        assert r.status_code == 404


# ------------- all four actions are independent of the roster --------------
@pytest.mark.asyncio
class TestNoRosterDependency:
    """The dashboard is now the primary way orders are driven, so every action
    must work with an EMPTY testers table and auto-advance switched off. None of
    them consults the roster — this proves it rather than asserting the design.
    """

    @pytest.fixture(autouse=True)
    def _manual_only(self):
        prev = settings.AUTO_ADVANCE_ROSTER_ORDERS
        settings.AUTO_ADVANCE_ROSTER_ORDERS = False
        yield
        settings.AUTO_ADVANCE_ROSTER_ORDERS = prev

    @pytest.fixture(autouse=True)
    async def _empty_roster(self, db):
        await db.execute(text("DELETE FROM testers"))
        await db.commit()

    async def _assert_roster_untouched(self, db):
        assert await db.scalar(text("SELECT count(*) FROM testers")) == 0
        assert await db.scalar(text(
            "SELECT count(*) FROM auto_advance_schedule")) == 0

    async def test_approve_then_ready_then_deliver_all_work_manually(
            self, client, seed, paid_order, db):
        await self._assert_roster_untouched(db)
        oid = paid_order["id"]

        assert (await client.post(f"{API}/testing/orders/{oid}/approve",
                                  headers=HDR)).json()["status"] == "RECEIVED"
        assert (await client.post(f"{API}/testing/orders/{oid}/approve",
                                  headers=HDR)).json()["status"] == "PREPARING"
        assert (await client.post(f"{API}/testing/orders/{oid}/ready",
                                  headers=HDR)).json()["status"] == "READY"
        # READY did NOT auto-complete: with nobody on the roster the auto-pickup
        # hook gates itself off, which is precisely why Delivered has to exist.
        assert await _db_status(db, oid) == "READY"

        assert (await client.post(f"{API}/testing/orders/{oid}/deliver",
                                  headers=HDR)).json()["status"] == "COMPLETED"
        assert await _db_status(db, oid) == "COMPLETED"
        await self._assert_roster_untouched(db)

    async def test_reject_works_manually_too(self, client, seed, paid_order, db):
        r = await client.post(f"{API}/testing/orders/{paid_order['id']}/reject",
                              headers=HDR, json={"reason": "manual"})
        assert r.json()["status"] == "CANCELLED"
        await self._assert_roster_untouched(db)

    async def test_the_flags_are_computed_without_consulting_the_roster(
            self, client, seed, paid_order, db):
        row = await _row(client, paid_order["id"])
        assert (row["can_approve"], row["can_ready"], row["can_deliver"],
                row["can_reject"]) == (True, False, True, True)
        await self._assert_roster_untouched(db)


# ------------------------------ the secret gate ---------------------------
@pytest.mark.asyncio
class TestActionsGated:
    async def test_approve_and_reject_require_the_key(self, client, seed, paid_order):
        a = await client.post(f"{API}/testing/orders/{paid_order['id']}/approve")
        j = await client.post(f"{API}/testing/orders/{paid_order['id']}/reject",
                              json={})
        assert a.status_code == 401 and j.status_code == 401

    async def test_ready_requires_the_key(self, client, seed, paid_order):
        # The gate is router-wide, but assert it per-route so a future move of
        # this endpoint off that router cannot silently open it.
        r = await client.post(f"{API}/testing/orders/{paid_order['id']}/ready")
        assert r.status_code == 401

    async def test_deliver_requires_the_key(self, client, seed, paid_order):
        r = await client.post(f"{API}/testing/orders/{paid_order['id']}/deliver")
        assert r.status_code == 401
