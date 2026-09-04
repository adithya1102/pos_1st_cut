"""Roster-scoped auto-progression of orders (testing only) — DURABLE version.

The next stage + due time live in auto_advance_schedule (migration 028); a poller
advances due rows, so progression survives a backend restart. The roster matches
by identifier = COALESCE(phone_number, email) (migration 027), so a Google-only
(email) tester is covered identically to a phone (OTP) one.

Held here (the mission's cases):
  * roster order + flag ON  -> advances through every stage automatically, ends
    picked-up (COMPLETED via the real verify_pickup path), no manual call;
  * roster order + flag OFF -> stays manual (PAID), nothing scheduled;
  * NON-roster order + flag ON -> stays manual regardless;
  * a gap of AUTO_ADVANCE_DELAY_SECONDS precedes each stage (asserted on due_at);
  * EMAIL-only tester -> add / auto-advance / auto-pickup all work identically;
  * a simulated restart mid-progression -> the order resumes from the persisted
    stage and completes with no manual intervention;
  * a roster order mid-progression is still visible in owner_app's queue.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.carevo_customer.deps import create_customer_token
from app.modules.carevo_customer.service import CarevoService
from app.modules.testing_dashboard import service as td
from app.modules.testing_dashboard.service import TestingService

API = "/api/v1"


@pytest.fixture
def auto_flag():
    """Own the knobs for one test and always restore them, so no test leaks the
    switch or a tuned delay into another."""
    prev = (settings.AUTO_ADVANCE_ROSTER_ORDERS,
            settings.AUTO_ADVANCE_DELAY_SECONDS)
    yield settings
    (settings.AUTO_ADVANCE_ROSTER_ORDERS,
     settings.AUTO_ADVANCE_DELAY_SECONDS) = prev


@pytest.fixture(autouse=True)
async def _clean_schedule(db):
    """Start each test with an empty schedule table, so driving the poller with a
    far-future clock only ever touches rows the current test created."""
    await db.execute(text("DELETE FROM auto_advance_schedule"))
    await db.commit()
    yield


# --------------------------------- helpers --------------------------------
async def _order_and_pay(client, headers, seed):
    r = await client.post(f"{API}/customer/orders", headers=headers,
                          json={"outlet_id": seed["outlet_id"],
                                "items": [{"menu_item_id": seed["menu_item_id"],
                                           "quantity": 1}]})
    assert r.status_code == 200, r.text
    order = r.json()
    p = await client.post(f"{API}/customer/payment/simulate", headers=headers,
                          json={"order_id": order["id"], "method": "upi"})
    assert p.status_code == 200, p.text
    return order


async def _pay_seed_order(client, seed, db, *, on_roster: bool):
    """Pay an order for the seed (phone) customer; optionally add them to the
    roster BEFORE payment so the PAID trigger sees a tester."""
    phone = await db.scalar(text(
        "SELECT phone_number FROM customers WHERE id = :c"),
        {"c": seed["customer_id"]})
    if on_roster:
        await TestingService.add_tester(db, phone, "Tester")
    return await _order_and_pay(client, seed["customer_auth"], seed), phone


async def _status(db, order_id) -> str:
    return await db.scalar(text(
        "SELECT status FROM customer_orders WHERE id = :o"), {"o": order_id})


async def _has_schedule(db, order_id) -> bool:
    return (await db.scalar(text(
        "SELECT count(*) FROM auto_advance_schedule WHERE order_id = :o"),
        {"o": order_id})) > 0


async def _poll_until_settled(db, order_id, *, passes=12):
    """Drive the durable poller with a far-future clock so due steps fire without
    real waiting — exactly what the background loop does, just time-collapsed."""
    for _ in range(passes):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await TestingService.process_due_auto_advances(db, now=future)
        if not await _has_schedule(db, order_id):
            return


async def _pickup_verified(db, order_id) -> bool:
    ev = await db.scalar(text(
        "SELECT count(*) FROM order_events WHERE order_id = :o "
        "AND event_type = 'PICKUP_VERIFIED'"), {"o": order_id})
    vat = await db.scalar(text(
        "SELECT pickup_verified_at FROM customer_orders WHERE id = :o"),
        {"o": order_id})
    return ev == 1 and vat is not None


# =============================== phone roster =============================
@pytest.mark.asyncio
class TestRosterAutoAdvance:
    async def test_flag_on_advances_all_the_way_to_pickup(
            self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = True
        auto_flag.AUTO_ADVANCE_DELAY_SECONDS = 20
        order, _ = await _pay_seed_order(client, seed, db, on_roster=True)

        # Payment persisted a schedule row; drive the poller (no manual advance).
        assert await _has_schedule(db, order["id"])
        await _poll_until_settled(db, order["id"])

        assert await _status(db, order["id"]) == "COMPLETED"
        assert await _pickup_verified(db, order["id"]), \
            "must complete via the real verify_pickup path, not a shortcut"
        assert not await _has_schedule(db, order["id"]), \
            "the schedule row is removed once the order is done"

    async def test_flag_off_stays_manual(self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = False
        order, _ = await _pay_seed_order(client, seed, db, on_roster=True)

        assert not await _has_schedule(db, order["id"]), \
            "flag off: nothing is scheduled"
        await _poll_until_settled(db, order["id"])
        assert await _status(db, order["id"]) == "PAID"

    async def test_non_roster_flag_on_stays_manual(
            self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = True
        auto_flag.AUTO_ADVANCE_DELAY_SECONDS = 0
        order, _ = await _pay_seed_order(client, seed, db, on_roster=False)

        assert not await _has_schedule(db, order["id"]), \
            "a non-roster order is never scheduled, even with the flag on"
        await _poll_until_settled(db, order["id"])
        assert await _status(db, order["id"]) == "PAID"

    async def test_a_delay_precedes_each_stage(
            self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = True
        auto_flag.AUTO_ADVANCE_DELAY_SECONDS = 20

        before = datetime.now(timezone.utc)
        order, _ = await _pay_seed_order(client, seed, db, on_roster=True)
        after = datetime.now(timezone.utc)

        # The first stage is due ~20s after it was scheduled.
        due1 = await db.scalar(text(
            "SELECT due_at FROM auto_advance_schedule WHERE order_id = :o"),
            {"o": order["id"]})
        assert before + timedelta(seconds=18) <= due1 <= after + timedelta(seconds=22)

        # Process one due step; the NEXT stage gets a fresh ~20s gap too.
        b2 = datetime.now(timezone.utc)
        await TestingService.process_due_auto_advances(
            db, now=datetime.now(timezone.utc) + timedelta(hours=1))
        a2 = datetime.now(timezone.utc)
        row2 = (await db.execute(text(
            "SELECT next_stage, due_at FROM auto_advance_schedule "
            "WHERE order_id = :o"), {"o": order["id"]})).first()
        assert row2.next_stage == "PREPARING"
        assert b2 + timedelta(seconds=18) <= row2.due_at <= a2 + timedelta(seconds=22)

        await _poll_until_settled(db, order["id"])  # finish + clean up the row

    async def test_owner_queue_shows_roster_order_mid_progression(
            self, client, seed, db, auto_flag):
        # Staff visibility isn't hidden: a roster order at PREPARING still appears
        # in owner_app's queue. Advance manually here so the state is exact; the
        # queue query neither knows nor cares who advanced it.
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = False
        order, _ = await _pay_seed_order(client, seed, db, on_roster=True)
        await CarevoService.advance_status(
            db, uuid.UUID(order["id"]), target="PREPARING")

        r = await client.get(f"{API}/pos/orders", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        row = next((o for o in r.json()
                    if str(o["order_id"]) == order["id"]), None)
        assert row is not None, "a roster order mid-progression must show to staff"
        assert row["status"] == "PREPARING"
        assert row["payment_status"] == "PAID"


# =============================== email roster ============================
@pytest.mark.asyncio
class TestEmailRosterParity:
    async def _email_customer(self, db, seed):
        """A Google-style customer: email + google_uid, NO phone — so its roster
        identifier is COALESCE(phone, email) = the email. google_uid is required
        by the customers_identity_present check (migration 008)."""
        cid = uuid.uuid4()
        email = f"tester_{seed['tag']}_{cid.hex[:6]}@gmail.com"
        await db.execute(text(
            "INSERT INTO customers (id, email, google_uid, name, points_balance, "
            "created_at) VALUES (:i, :e, :g, :n, 0, now())"),
            {"i": str(cid), "e": email, "g": f"google-{cid.hex}", "n": "Email Tester"})
        await db.commit()
        headers = {"Authorization": f"Bearer {create_customer_token(str(cid))}"}
        return str(cid), email, headers

    async def test_add_by_email_stores_identifier(self, seed, db):
        _, email, _ = await self._email_customer(db, seed)
        row = await TestingService.add_tester(db, email, "By email")
        assert row["identifier"] == email
        assert row["phone_number"] is None, "an email identifier leaves phone NULL"
        assert await TestingService.is_roster_identifier(db, email) is True
        listed = await TestingService.list_testers(db)
        assert any(t["identifier"] == email and t["phone_number"] is None
                   for t in listed)

    async def test_email_tester_auto_advances_and_picks_up(
            self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = True
        auto_flag.AUTO_ADVANCE_DELAY_SECONDS = 20
        _, email, headers = await self._email_customer(db, seed)
        await TestingService.add_tester(db, email, "Email Tester")

        order = await _order_and_pay(client, headers, seed)

        # Scheduled + driven purely off the email match — identical to phone.
        assert await _has_schedule(db, order["id"])
        await _poll_until_settled(db, order["id"])

        assert await _status(db, order["id"]) == "COMPLETED"
        assert await _pickup_verified(db, order["id"])


# ============================ durability / restart =======================
@pytest.mark.asyncio
class TestRestartResumes:
    async def test_resumes_from_persisted_stage_after_restart(
            self, client, seed, db, auto_flag):
        auto_flag.AUTO_ADVANCE_ROSTER_ORDERS = True
        auto_flag.AUTO_ADVANCE_DELAY_SECONDS = 20
        order, _ = await _pay_seed_order(client, seed, db, on_roster=True)

        # Advance ONE stage, then stop — the order is now mid-progression with its
        # next stage persisted in the DB (nothing is in memory).
        await TestingService.process_due_auto_advances(
            db, now=datetime.now(timezone.utc) + timedelta(hours=1))
        assert await _status(db, order["id"]) == "RECEIVED"
        row = (await db.execute(text(
            "SELECT next_stage FROM auto_advance_schedule WHERE order_id = :o"),
            {"o": order["id"]})).first()
        assert row.next_stage == "PREPARING", "next stage is persisted, not in RAM"

        # Simulate a restart: a BRAND-NEW session/process with no carried-over
        # task. The only thing that can resume the order is the persisted row.
        async with AsyncSessionLocal() as fresh_db:
            for _ in range(12):
                await TestingService.process_due_auto_advances(
                    fresh_db, now=datetime.now(timezone.utc) + timedelta(hours=1))
                still = await fresh_db.scalar(text(
                    "SELECT count(*) FROM auto_advance_schedule WHERE order_id=:o"),
                    {"o": order["id"]})
                if not still:
                    break

        assert await _status(db, order["id"]) == "COMPLETED", \
            "a restart mid-progression must resume from the DB and finish"
        assert await _pickup_verified(db, order["id"])
