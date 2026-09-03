"""Restaurant operating hours + manual-closed toggle (migration 024).

Holds the whole gate:
  * the pure availability logic (open / closing_soon / closed), clock-injected
    so the window and cutoff maths are deterministic;
  * order creation is refused when manually closed, outside hours, or within the
    pre-close cutoff, and allowed when open or when no schedule is set;
  * /customer/outlets surfaces the status label;
  * the owner can read/set hours and toggle the manual closure.
"""
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.modules.carevo_customer.service import (
    CarevoService, ORDER_CUTOFF_MINUTES,
    AVAIL_OPEN, AVAIL_CLOSING_SOON, AVAIL_CLOSED,
)

API = "/api/v1"
IST = ZoneInfo("Asia/Kolkata")


def _now(h, m):
    """A tz-aware 'now' on an arbitrary date, for the pure helper."""
    return datetime(2026, 1, 1, h, m, tzinfo=IST)


class TestAvailabilityLogic:
    def test_no_schedule_is_open(self):
        assert CarevoService.outlet_availability(None, None, False)["status"] == AVAIL_OPEN

    def test_manually_closed_beats_everything(self):
        r = CarevoService.outlet_availability(time(9, 0), time(22, 0), True,
                                              now=_now(13, 0))
        assert r["status"] == AVAIL_CLOSED
        assert "temporarily closed" in r["reason"]

    def test_open_midday(self):
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False, now=_now(13, 0))["status"] == AVAIL_OPEN

    def test_before_open_is_closed(self):
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False, now=_now(8, 0))["status"] == AVAIL_CLOSED

    def test_after_close_is_closed(self):
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False, now=_now(22, 30))["status"] == AVAIL_CLOSED

    def test_within_cutoff_is_closing_soon(self):
        # 15 min before close, cutoff is 30 -> closing_soon.
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False, now=_now(21, 45))["status"] == AVAIL_CLOSING_SOON

    def test_exactly_at_cutoff_is_closing_soon(self):
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False,
            now=_now(21, 60 - ORDER_CUTOFF_MINUTES))["status"] == AVAIL_CLOSING_SOON

    def test_one_minute_outside_cutoff_is_open(self):
        assert CarevoService.outlet_availability(
            time(9, 0), time(22, 0), False,
            now=_now(21, 60 - ORDER_CUTOFF_MINUTES - 1))["status"] == AVAIL_OPEN

    def test_overnight_open(self):
        # 18:00 -> 02:00, now 01:00 is inside the wrapped window.
        assert CarevoService.outlet_availability(
            time(18, 0), time(2, 0), False, now=_now(1, 0))["status"] == AVAIL_OPEN

    def test_overnight_closing_soon(self):
        assert CarevoService.outlet_availability(
            time(18, 0), time(2, 0), False, now=_now(1, 45))["status"] == AVAIL_CLOSING_SOON

    def test_overnight_closed_in_the_afternoon(self):
        assert CarevoService.outlet_availability(
            time(18, 0), time(2, 0), False, now=_now(15, 0))["status"] == AVAIL_CLOSED


async def _set_hours(db, outlet_id, opens, closes, manual=False):
    await db.execute(text(
        "UPDATE outlets SET opens_at=:o, closes_at=:c, is_manually_closed=:m "
        "WHERE id=:id"),
        {"o": opens, "c": closes, "m": manual, "id": str(outlet_id)})
    await db.commit()


def _t(delta_minutes: int) -> time:
    """A bare local time offset from NOW (IST) by delta_minutes. The service
    handles midnight wrap, so a negative/large offset near midnight is fine."""
    return (datetime.now(IST) + timedelta(minutes=delta_minutes)).time().replace(
        second=0, microsecond=0)


async def _place(client, seed):
    return await client.post(f"{API}/customer/orders", headers=seed["customer_auth"],
                             json={"outlet_id": seed["outlet_id"],
                                   "items": [{"menu_item_id": seed["menu_item_id"],
                                              "quantity": 1}]})


@pytest.mark.asyncio
class TestOrderGate:
    async def test_allowed_when_no_schedule(self, client, seed):
        # Every existing outlet (NULL hours) keeps accepting orders.
        r = await _place(client, seed)
        assert r.status_code == 200, r.text

    async def test_rejected_when_manually_closed(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], None, None, manual=True)
        r = await _place(client, seed)
        assert r.status_code == 409
        assert "temporarily closed" in r.json()["detail"].lower()

    async def test_rejected_when_closed_outside_hours(self, client, seed, db):
        # Opened 3h ago, closed 20 min ago.
        await _set_hours(db, seed["outlet_id"], _t(-180), _t(-20))
        r = await _place(client, seed)
        assert r.status_code == 409
        assert "closed" in r.json()["detail"].lower()

    async def test_rejected_when_closing_soon(self, client, seed, db):
        # Closes in 10 min — inside the 30-min cutoff.
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(10))
        r = await _place(client, seed)
        assert r.status_code == 409
        assert "closing soon" in r.json()["detail"].lower()

    async def test_allowed_when_open_and_outside_cutoff(self, client, seed, db):
        # Open for another 2h — comfortably outside the cutoff.
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(120))
        r = await _place(client, seed)
        assert r.status_code == 200, r.text

    async def test_a_rejected_order_writes_no_row(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], None, None, manual=True)
        before = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id=:o"),
            {"o": seed["outlet_id"]})
        await _place(client, seed)
        after = await db.scalar(text(
            "SELECT count(*) FROM customer_orders WHERE outlet_id=:o"),
            {"o": seed["outlet_id"]})
        assert after == before, "a gated order must not leave a CREATED row behind"


@pytest.mark.asyncio
class TestCustomerListingStatus:
    async def _seed_card(self, client, seed):
        r = await client.get(f"{API}/customer/outlets",
                             headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        return next((o for o in r.json()
                     if str(o["id"]) == str(seed["outlet_id"])), None)

    async def test_manual_closed_shows_closed(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], None, None, manual=True)
        card = await self._seed_card(client, seed)
        assert card is not None
        assert card["order_status"] == AVAIL_CLOSED
        assert card["is_open"] is False
        assert "temporarily closed" in card["closed_reason"].lower()

    async def test_open_window_shows_open(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(120))
        card = await self._seed_card(client, seed)
        assert card["order_status"] == AVAIL_OPEN
        assert card["is_open"] is True

    async def test_closing_soon_shows_closing_soon(self, client, seed, db):
        await _set_hours(db, seed["outlet_id"], _t(-120), _t(10))
        card = await self._seed_card(client, seed)
        assert card["order_status"] == AVAIL_CLOSING_SOON
        assert card["is_open"] is False


@pytest.mark.asyncio
class TestOwnerHoursEndpoints:
    async def test_get_returns_hours_fields(self, client, seed):
        r = await client.get(f"{API}/pos/outlet", headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("opening_time", "closing_time", "is_manually_closed", "order_status"):
            assert k in body
        assert body["is_manually_closed"] is False  # default

    async def test_owner_can_set_hours(self, client, seed):
        r = await client.patch(f"{API}/pos/outlet/hours", headers=seed["owner_auth"],
                              json={"opening_time": "09:00", "closing_time": "22:00"})
        assert r.status_code == 200, r.text
        assert r.json()["opening_time"] == "09:00"
        assert r.json()["closing_time"] == "22:00"
        # And it persisted.
        g = await client.get(f"{API}/pos/outlet", headers=seed["owner_auth"])
        assert g.json()["closing_time"] == "22:00"

    async def test_bad_time_is_rejected(self, client, seed):
        r = await client.patch(f"{API}/pos/outlet/hours", headers=seed["owner_auth"],
                              json={"opening_time": "9am", "closing_time": "22:00"})
        assert r.status_code == 422

    async def test_owner_can_toggle_manual_closure(self, client, seed):
        r = await client.post(f"{API}/pos/outlet/closed", headers=seed["owner_auth"],
                             json={"is_manually_closed": True})
        assert r.status_code == 200, r.text
        assert r.json()["is_manually_closed"] is True
        assert r.json()["order_status"] == AVAIL_CLOSED

        # And flipping it back re-opens (no schedule set -> open).
        r2 = await client.post(f"{API}/pos/outlet/closed", headers=seed["owner_auth"],
                              json={"is_manually_closed": False})
        assert r2.json()["is_manually_closed"] is False
        assert r2.json()["order_status"] == AVAIL_OPEN

    async def test_setting_hours_does_not_touch_visibility_or_photo(
            self, client, seed, db):
        # Give the outlet a photo + visibility first, then set hours.
        await db.execute(text(
            "UPDATE outlets SET image_url='http://x/y.png', is_visible=true "
            "WHERE id=:id"), {"id": seed["outlet_id"]})
        await db.commit()
        r = await client.patch(f"{API}/pos/outlet/hours", headers=seed["owner_auth"],
                              json={"opening_time": "08:00", "closing_time": "20:00"})
        body = r.json()
        assert body["image_url"] == "http://x/y.png"
        assert body["is_visible"] is True
