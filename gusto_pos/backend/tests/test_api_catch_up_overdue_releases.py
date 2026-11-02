"""Task 3(a) — catch_up_overdue_releases (testing_dashboard/service.py:939).

Called once, awaited, from app/main.py's on_startup, BEFORE the background
auto_advance_poller_loop task is even scheduled — closing the race where a
scheduled pickup matured during a redeploy or a Render free-tier sleep and
would otherwise sit held until the poller's own first tick (see the
function's own docstring). No prior test in this suite called this function
directly; every other scheduled-pickup test (test_api_scheduled_pickup.py)
exercises the poller's two steps (refresh_scheduled_releases +
process_due_auto_advances) separately, never this startup wrapper.

Reuses the scheduled-pickup suite's own helpers (_place_and_pay, _make_due,
_schedule_row, _row) rather than redefining them — the same cross-import
pattern test_api_stock_hold_ttl.py already uses against
test_api_stock_reservation.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.testing_dashboard.service import catch_up_overdue_releases
from tests.test_api_scheduled_pickup import (
    _iso,
    _make_due,
    _place_and_pay,
    _row,
    _schedule_row,
)


@pytest.mark.asyncio
class TestCatchUpOverdueReleases:
    async def test_past_due_held_order_is_released_at_startup(
            self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        await _make_due(db, order["id"])
        # Sanity: still held, release row still due, before the catch-up runs.
        assert (await _row(db, order["id"])).status == "PAID"
        assert await _schedule_row(db, order["id"]) is not None

        # NOT asserted on the return value: catch_up_overdue_releases reports
        # only what process_due_auto_advances processed, but the SAME order
        # can instead be released a step earlier, inside the preceding
        # refresh_scheduled_releases call (service.py:3751-3756), whenever
        # that pass's own twin-based estimate already finds it due — which
        # depends on backlog data this suite's own earlier tests leave behind
        # and is not this test's concern. Either path is a correct release;
        # the order's actual state is the only thing worth pinning here.
        await catch_up_overdue_releases(db)

        assert (await _row(db, order["id"])).status == "RECEIVED", (
            "a past-due held order was not released by the startup catch-up"
        )
        assert await _schedule_row(db, order["id"]) is None, (
            "the release row must be deleted once the catch-up processes it"
        )

    async def test_not_yet_due_order_is_untouched(self, client, seed, db):
        order = await _place_and_pay(client, seed, requested_pickup_at=_iso(
            datetime.now(timezone.utc) + timedelta(minutes=120)))
        # Deliberately NOT calling _make_due: due_at stays in the future.
        before = await _row(db, order["id"])
        assert before.status == "PAID"
        before_schedule = await _schedule_row(db, order["id"])
        assert before_schedule is not None

        await catch_up_overdue_releases(db)

        after = await _row(db, order["id"])
        assert after.status == "PAID", (
            "the startup catch-up released an order that was not due yet"
        )
        after_schedule = await _schedule_row(db, order["id"])
        assert after_schedule is not None
        assert after_schedule.due_at == before_schedule.due_at
