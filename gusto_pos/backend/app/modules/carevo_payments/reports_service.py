"""TASK 7 — reconciliation reports.

ADDITIVE, read-only. Every number here is derived from this layer's OWN
records (customer_orders' payment/status columns, payment_events,
service_fee_ledger) -- never from a bank statement or a provider dashboard.
That is the literal point of the "basis" field every report carries.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BASIS = "verified payment evidence, not bank settlement"

_DAILY_REPORT_SQL = """
WITH day_orders AS (
    SELECT id, status, payment_status, vendor_payment_confirmed_at
      FROM customer_orders
     WHERE outlet_id = :outlet_id
       AND (created_at AT TIME ZONE 'Asia/Kolkata')::date = :day
),
day_events AS (
    SELECT outcome, reason
      FROM payment_events
     WHERE outlet_id = :outlet_id
       AND (received_at AT TIME ZONE 'Asia/Kolkata')::date = :day
),
day_fees AS (
    SELECT entry_type, amount_paise
      FROM service_fee_ledger
     WHERE outlet_id = :outlet_id
       AND (created_at AT TIME ZONE 'Asia/Kolkata')::date = :day
)
SELECT
    (SELECT count(*) FROM day_orders) AS total_orders,
    (SELECT count(*) FROM day_orders
      WHERE payment_status = 'PAID' OR vendor_payment_confirmed_at IS NOT NULL
    ) AS verified_payments,
    (SELECT count(*) FROM day_events WHERE outcome = 'IGNORED' AND reason = 'status_failed') AS failed,
    (SELECT count(*) FROM day_events WHERE outcome = 'IGNORED' AND reason = 'status_pending') AS pending,
    (SELECT count(*) FROM day_events WHERE outcome = 'REVIEW' AND reason = 'amount_mismatch') AS mismatches,
    (SELECT count(*) FROM day_events WHERE outcome = 'DUPLICATE') AS duplicates,
    (SELECT count(*) FROM day_orders
      WHERE upper(status) IN ('PICKED_UP', 'COMPLETED')
        AND (payment_status = 'PAID' OR vendor_payment_confirmed_at IS NOT NULL)
    ) AS eligible_orders,
    (SELECT coalesce(sum(
            CASE entry_type WHEN 'CHARGE' THEN amount_paise ELSE -amount_paise END
        ), 0) FROM day_fees) AS fees_paise
"""


async def daily_report(db: AsyncSession, *, outlet_id, date_str: str) -> dict:
    day = _date.fromisoformat(date_str)
    row = (await db.execute(text(_DAILY_REPORT_SQL),
                             {"outlet_id": str(outlet_id), "day": day})).first()
    return {
        "outlet_id": str(outlet_id),
        "date": date_str,
        "total_orders": row[0],
        "verified_payments": row[1],
        "failed": row[2],
        "pending": row[3],
        "mismatches": row[4],
        "duplicates": row[5],
        "eligible_orders": row[6],
        "fees_paise": int(row[7]),
        "basis": BASIS,
    }


async def daily_report_all_outlets(db: AsyncSession, *, date_str: str) -> list[dict]:
    day = _date.fromisoformat(date_str)
    outlet_ids = (await db.execute(text("""
        SELECT DISTINCT outlet_id FROM customer_orders
         WHERE (created_at AT TIME ZONE 'Asia/Kolkata')::date = :day
    """), {"day": day})).fetchall()
    return [
        await daily_report(db, outlet_id=row[0], date_str=date_str)
        for row in outlet_ids
    ]


async def fee_ledger_rows(db: AsyncSession, outlet_id, *, limit: int = 200) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT id, order_id, entry_type, amount_paise, billing_period,
               status, invoice_ref, created_at
          FROM service_fee_ledger
         WHERE outlet_id = :outlet_id
         ORDER BY created_at DESC
         LIMIT :lim
    """), {"outlet_id": str(outlet_id), "lim": limit})).fetchall()
    return [
        {
            "id": str(r[0]), "order_id": str(r[1]), "entry_type": r[2],
            "amount_paise": r[3], "billing_period": r[4], "status": r[5],
            "invoice_ref": r[6], "created_at": r[7],
        }
        for r in rows
    ]
