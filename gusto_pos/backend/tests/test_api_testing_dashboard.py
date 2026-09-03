"""Local testing dashboard (migration 025) + roster-scoped auto-pickup.

Holds four things the mission calls out:
  * every dashboard endpoint is rejected without the correct X-Testing-Key;
  * auto-pickup fires for a ROSTER phone reaching READY and does NOT fire for a
    non-roster phone (the negative case is asserted explicitly);
  * the 23:00-IST compliance window counts a 23:30 order in the right day;
  * roster CRUD works.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_customer.service import CarevoService
from app.modules.testing_dashboard.service import (
    TestingService, current_window, TESTING_TZ,
)

API = "/api/v1"
KEY = "test-dash-key"
HDR = {"X-Testing-Key": KEY}


@pytest.fixture(autouse=True)
def _configure_key():
    """The gate reads settings at request time; set a known key for the suite
    and restore afterwards so no other test sees it."""
    prev = settings.TESTING_DASHBOARD_KEY
    settings.TESTING_DASHBOARD_KEY = KEY
    yield
    settings.TESTING_DASHBOARD_KEY = prev


async def _customer_phone(db, customer_id) -> str:
    return await db.scalar(text(
        "SELECT phone_number FROM customers WHERE id = :c"), {"c": customer_id})


# ============================ the secret gate ==============================
@pytest.mark.asyncio
class TestSecretGate:
    async def test_no_header_is_401(self, client):
        r = await client.get(f"{API}/testing/outlets")
        assert r.status_code == 401

    async def test_wrong_header_is_401(self, client):
        r = await client.get(f"{API}/testing/outlets",
                             headers={"X-Testing-Key": "nope"})
        assert r.status_code == 401

    async def test_correct_header_passes(self, client, seed):
        r = await client.get(f"{API}/testing/outlets", headers=HDR)
        assert r.status_code == 200

    async def test_fail_closed_when_key_unset(self, client):
        # Even a caller sending *a* header is rejected while the server key is
        # empty — the dashboard never becomes open by omission.
        settings.TESTING_DASHBOARD_KEY = ""
        r = await client.get(f"{API}/testing/orders", headers=HDR)
        assert r.status_code == 401

    async def test_every_route_is_gated(self, client):
        for method, path in [
            ("GET", "/testing/outlets"), ("GET", "/testing/orders"),
            ("GET", "/testing/testers"), ("GET", "/testing/compliance"),
        ]:
            r = await client.request(method, f"{API}{path}")
            assert r.status_code == 401, f"{path} was not gated"


# ============================== roster CRUD ================================
@pytest.mark.asyncio
class TestRosterCrud:
    async def test_add_list_remove(self, client, seed):
        phone = "+919000000123"
        add = await client.post(f"{API}/testing/testers", headers=HDR,
                                json={"phone_number": phone, "name": "Asha"})
        assert add.status_code == 200
        assert add.json()["phone_number"] == phone

        listed = await client.get(f"{API}/testing/testers", headers=HDR)
        assert any(t["phone_number"] == phone for t in listed.json())

        rm = await client.delete(f"{API}/testing/testers/{phone}", headers=HDR)
        assert rm.status_code == 200 and rm.json()["removed"] == 1

        listed2 = await client.get(f"{API}/testing/testers", headers=HDR)
        assert not any(t["phone_number"] == phone for t in listed2.json())

    async def test_add_is_idempotent(self, client, seed, db):
        phone = "+919000000999"
        await client.post(f"{API}/testing/testers", headers=HDR,
                         json={"phone_number": phone})
        await client.post(f"{API}/testing/testers", headers=HDR,
                         json={"phone_number": phone, "name": "Renamed"})
        n = await db.scalar(text(
            "SELECT count(*) FROM testers WHERE phone_number=:p"), {"p": phone})
        assert n == 1


# =========================== auto-pickup scope =============================
@pytest.mark.asyncio
class TestAutoPickupRosterScoped:
    async def test_fires_for_a_roster_phone(self, client, seed, paid_order, db):
        phone = await _customer_phone(db, seed["customer_id"])
        await TestingService.add_tester(db, phone, "Tester")

        # Reaching READY must auto-complete it via verify_pickup.
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")

        status = await db.scalar(text(
            "SELECT status FROM customer_orders WHERE id=:o"),
            {"o": paid_order["id"]})
        assert status == "COMPLETED", "a roster order should auto-pickup at READY"
        # And it went through the real path: PICKUP_VERIFIED event + timestamp.
        ev = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='PICKUP_VERIFIED'"), {"o": paid_order["id"]})
        assert ev == 1
        vat = await db.scalar(text(
            "SELECT pickup_verified_at FROM customer_orders WHERE id=:o"),
            {"o": paid_order["id"]})
        assert vat is not None

    async def test_does_NOT_fire_for_a_non_roster_phone(
            self, client, seed, paid_order, db):
        # Roster has a DIFFERENT number; this customer is not on it.
        await TestingService.add_tester(db, "+910000000000", "Someone else")

        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")

        status = await db.scalar(text(
            "SELECT status FROM customer_orders WHERE id=:o"),
            {"o": paid_order["id"]})
        assert status == "READY", "a non-roster order must NOT be auto-completed"
        ev = await db.scalar(text(
            "SELECT count(*) FROM order_events WHERE order_id=:o "
            "AND event_type='PICKUP_VERIFIED'"), {"o": paid_order["id"]})
        assert ev == 0

    async def test_empty_roster_completes_nothing(self, seed, paid_order, db):
        await CarevoService.advance_status(
            db, uuid.UUID(paid_order["id"]), target="READY")
        status = await db.scalar(text(
            "SELECT status FROM customer_orders WHERE id=:o"),
            {"o": paid_order["id"]})
        assert status == "READY"


# ======================= compliance window boundary =======================
class TestComplianceWindowLogic:
    def _ist(self, y, mo, d, h, mi):
        return datetime(y, mo, d, h, mi, tzinfo=TESTING_TZ)

    def test_2330_order_counts_in_the_window_that_started_at_2300(self):
        # It is 23:45 on Jan 10; the window began at 23:00 Jan 10.
        start, end = current_window(self._ist(2026, 1, 10, 23, 45))
        boundary = self._ist(2026, 1, 10, 23, 0).astimezone(timezone.utc)
        assert start == boundary
        order_2330 = self._ist(2026, 1, 10, 23, 30).astimezone(timezone.utc)
        assert start <= order_2330 < end, \
            "a 23:30 order belongs to the window opened at 23:00 that evening"

    def test_2259_order_is_in_the_previous_window(self):
        # Just before boundary on Jan 10: still in the window opened Jan 9 23:00.
        start, end = current_window(self._ist(2026, 1, 10, 22, 59))
        assert start == self._ist(2026, 1, 9, 23, 0).astimezone(timezone.utc)
        just_before = self._ist(2026, 1, 10, 22, 59).astimezone(timezone.utc)
        assert start <= just_before < end
        # And a 23:30 order that same evening is in the NEXT window, not this one.
        after_boundary = self._ist(2026, 1, 10, 23, 30).astimezone(timezone.utc)
        assert not (start <= after_boundary < end)

    def test_window_is_exactly_24h(self):
        start, end = current_window(self._ist(2026, 6, 1, 12, 0))
        assert end - start == timedelta(days=1)


@pytest.mark.asyncio
class TestComplianceEndpoint:
    async def test_orderer_and_non_orderer_split_correctly(
            self, client, seed, paid_order, db):
        # The seed customer just placed paid_order (created now -> in window).
        phone = await _customer_phone(db, seed["customer_id"])
        await TestingService.add_tester(db, phone, "Ordered")
        await TestingService.add_tester(db, "+919111111111", "Idle")

        r = await client.get(f"{API}/testing/compliance", headers=HDR)
        assert r.status_code == 200
        body = r.json()
        ordered = {t["phone_number"] for t in body["ordered"]}
        not_ordered = {t["phone_number"] for t in body["not_ordered"]}
        assert phone in ordered
        assert "+919111111111" in not_ordered
        assert phone not in not_ordered
