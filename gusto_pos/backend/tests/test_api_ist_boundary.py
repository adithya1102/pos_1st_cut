"""TASK 9 (reconcile fix pass) — the daily report's IST day boundary.

reports_service.daily_report buckets by `(created_at AT TIME ZONE
'Asia/Kolkata')::date`. IST is UTC+5:30, so 18:30:00 UTC is exactly
midnight IST -- the instant the calendar date rolls over. One second
earlier (18:29:59 UTC) is still 23:59:59 IST on the PRIOR date.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.modules.carevo_payments import reports_service as rs

pytestmark = pytest.mark.asyncio

IST_SAME_DAY = "2026-01-15"   # 18:29:59 UTC on this date -> still this IST date
IST_NEXT_DAY = "2026-01-16"   # 18:30:00 UTC on this date -> rolls to this IST date

_ONE_SECOND_BEFORE_MIDNIGHT_IST = datetime(2026, 1, 15, 18, 29, 59, tzinfo=timezone.utc)
_EXACTLY_MIDNIGHT_IST = datetime(2026, 1, 15, 18, 30, 0, tzinfo=timezone.utc)


async def _insert_order(db, *, outlet_id, customer_id, created_at_utc: datetime) -> str:
    order_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO customer_orders
            (id, customer_id, outlet_id, status, total_amount, payment_status,
             created_at, updated_at)
        VALUES (:id, :cust, :outlet, 'COMPLETED', 100, 'PAID',
                :created_at, :created_at)
    """), {"id": str(order_id), "cust": str(customer_id), "outlet": str(outlet_id),
           "created_at": created_at_utc})
    await db.commit()
    return str(order_id)


class TestISTDayBoundary:
    async def test_one_second_before_midnight_ist_counts_on_the_earlier_date(
            self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            created_at_utc=_ONE_SECOND_BEFORE_MIDNIGHT_IST)

        same_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_SAME_DAY)
        next_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_NEXT_DAY)

        assert same_day_report["total_orders"] == 1
        assert next_day_report["total_orders"] == 0

    async def test_exactly_midnight_ist_counts_on_the_next_date(self, db, seed):
        order_id = await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            created_at_utc=_EXACTLY_MIDNIGHT_IST)

        same_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_SAME_DAY)
        next_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_NEXT_DAY)

        assert same_day_report["total_orders"] == 0
        assert next_day_report["total_orders"] == 1

    async def test_both_fixtures_together_split_across_the_two_ist_dates(
            self, db, seed):
        await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            created_at_utc=_ONE_SECOND_BEFORE_MIDNIGHT_IST)
        await _insert_order(
            db, outlet_id=seed["outlet_id"], customer_id=seed["customer_id"],
            created_at_utc=_EXACTLY_MIDNIGHT_IST)

        same_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_SAME_DAY)
        next_day_report = await rs.daily_report(
            db, outlet_id=seed["outlet_id"], date_str=IST_NEXT_DAY)

        assert same_day_report["total_orders"] == 1
        assert next_day_report["total_orders"] == 1
