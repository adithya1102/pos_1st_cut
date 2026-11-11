"""TASK 6 — Rs 1 (default) service-fee ledger.

ADDITIVE. Depends on migration 041 (service_fee_ledger table + its chain/
immutability triggers and verify_chain/fn_advance_fee_entry_status
functions). Nothing existing calls this module; it is inert while
SERVICE_FEE_LEDGER_ENABLED is false (the default).

CareVo bills the VENDOR this fee per eligible order. CareVo never collects,
holds, splits, or settles the customer's payment to the vendor -- this
module only writes an audit-trail entry recording what the vendor owes the
platform.

BILLABLE EVENT (see migration 041's header for the exact status literal
and line citations): customer_orders.status = 'COMPLETED'
AND (customer_orders.payment_status = 'PAID' OR
customer_orders.vendor_payment_confirmed_at IS NOT NULL).

'PICKED_UP' is deliberately NOT in the billable set. It is never written to
customer_orders.status anywhere in this codebase -- see
app/modules/carevo_customer/service.py's record_picked_up (around line
2430): "Deliberately does NOT move order.status -- staff verifying the
pickup code (PICKUP_VERIFIED -> COMPLETED) remains the only real
completion." The only two places that ever set status = 'COMPLETED' are
CarevoService.verify_pickup (service.py line ~4343) and
CarevoService.collect_order (service.py line ~5223).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

_BILLABLE_STATUSES = {"COMPLETED"}


async def charge_if_eligible(db: AsyncSession, order_id, *, commit: bool = True) -> dict:
    """Charge the order's outlet the configured service fee, exactly once.

    UNIQUE(order_id, entry_type) + ON CONFLICT DO NOTHING is the concurrency
    primitive: two simultaneous calls for the same order (e.g. two
    concurrent requests both observing the order just became COMPLETED)
    race on the unique index, and only the one that actually inserts a row
    reports charged=True -- the other reports already_charged, having
    written nothing.

    commit=False lets a caller fold this into its OWN transaction (the
    COMPLETED status write), so a failure here rolls back the status change
    too -- see CarevoService.verify_pickup / collect_order. The default
    (commit=True) keeps this usable standalone, as every existing direct
    caller (tests, ad-hoc scripts) already relies on.
    """
    if not settings.SERVICE_FEE_LEDGER_ENABLED:
        return {"charged": False, "reason": "flag_off"}

    row = (await db.execute(text("""
        SELECT outlet_id, status, payment_status, vendor_payment_confirmed_at
          FROM customer_orders WHERE id = :id
    """), {"id": str(order_id)})).first()
    if row is None:
        return {"charged": False, "reason": "order_not_found"}

    outlet_id, status, payment_status, vendor_confirmed_at = row
    billable_status = (status or "").upper() in _BILLABLE_STATUSES
    payment_ok = (payment_status or "").upper() == "PAID" or vendor_confirmed_at is not None
    if not (billable_status and payment_ok):
        return {"charged": False, "reason": "not_billable"}

    res = await db.execute(text("""
        INSERT INTO service_fee_ledger
            (outlet_id, order_id, entry_type, amount_paise, billing_period)
        VALUES (:outlet_id, :order_id, 'CHARGE', :amount,
                to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM'))
        ON CONFLICT (order_id, entry_type) DO NOTHING
        RETURNING id
    """), {"outlet_id": str(outlet_id), "order_id": str(order_id),
           "amount": settings.SERVICE_FEE_PAISE})
    inserted = res.first()
    if commit:
        await db.commit()
    if inserted is None:
        return {"charged": False, "reason": "already_charged"}
    return {"charged": True, "entry_id": str(inserted[0]),
            "amount_paise": settings.SERVICE_FEE_PAISE}


async def reverse_if_charged(db: AsyncSession, order_id, *, commit: bool = True) -> dict:
    """Write a REVERSAL for an order that WAS charged. A refund after a
    charge is the only caller-visible trigger for this -- it does not
    re-check order status, since the charge already happened and the
    refund is a later fact about the SAME order, not a reason to pretend
    the charge never occurred.

    Same UNIQUE(order_id, entry_type) + ON CONFLICT DO NOTHING idempotency
    as charge_if_eligible: calling this twice for one order writes at most
    one REVERSAL row, ever. commit=False, same reasoning as
    charge_if_eligible: fold into the caller's own refund transaction.
    """
    if not settings.SERVICE_FEE_LEDGER_ENABLED:
        return {"reversed": False, "reason": "flag_off"}

    charge = (await db.execute(text("""
        SELECT outlet_id, amount_paise FROM service_fee_ledger
         WHERE order_id = :id AND entry_type = 'CHARGE'
    """), {"id": str(order_id)})).first()
    if charge is None:
        return {"reversed": False, "reason": "no_charge_to_reverse"}

    outlet_id, amount_paise = charge
    res = await db.execute(text("""
        INSERT INTO service_fee_ledger
            (outlet_id, order_id, entry_type, amount_paise, billing_period)
        VALUES (:outlet_id, :order_id, 'REVERSAL', :amount,
                to_char(now() AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM'))
        ON CONFLICT (order_id, entry_type) DO NOTHING
        RETURNING id
    """), {"outlet_id": str(outlet_id), "order_id": str(order_id), "amount": amount_paise})
    inserted = res.first()
    if commit:
        await db.commit()
    if inserted is None:
        return {"reversed": False, "reason": "already_reversed"}
    return {"reversed": True, "entry_id": str(inserted[0]), "amount_paise": amount_paise}


async def advance_status(db: AsyncSession, entry_id, status: str,
                          invoice_ref: Optional[str] = None) -> None:
    """The ONE sanctioned way to change status/invoice_ref -- calls
    fn_advance_fee_entry_status (migration 041), never a raw UPDATE."""
    await db.execute(text(
        "SELECT fn_advance_fee_entry_status(:id, :status, :ref)"),
        {"id": str(entry_id), "status": status, "ref": invoice_ref})
    await db.commit()


async def find_uncharged_completed(
    db: AsyncSession, outlet_id=None, since: Optional[datetime] = None,
) -> list[dict]:
    """Orders that are COMPLETED and eligible per the Task 1 rule
    (payment_status='PAID' OR vendor_payment_confirmed_at IS NOT NULL) but
    have no CHARGE row in service_fee_ledger -- a missed charge from a
    ledger failure, a flag that was off when the order completed and has
    since been turned on, or any other gap. `outlet_id`/`since` narrow the
    scan; both default to "every outlet, all time".
    """
    clauses = [
        "co.status = 'COMPLETED'",
        "(co.payment_status = 'PAID' OR co.vendor_payment_confirmed_at IS NOT NULL)",
        "NOT EXISTS (SELECT 1 FROM service_fee_ledger sfl "
        "WHERE sfl.order_id = co.id AND sfl.entry_type = 'CHARGE')",
    ]
    params: dict = {}
    if outlet_id is not None:
        clauses.append("co.outlet_id = :outlet_id")
        params["outlet_id"] = str(outlet_id)
    if since is not None:
        clauses.append("co.updated_at >= :since")
        params["since"] = since

    rows = (await db.execute(text(f"""
        SELECT co.id, co.outlet_id, co.updated_at
          FROM customer_orders co
         WHERE {' AND '.join(clauses)}
         ORDER BY co.updated_at ASC
    """), params)).fetchall()
    return [
        {"order_id": str(r[0]), "outlet_id": str(r[1]), "updated_at": r[2]}
        for r in rows
    ]


async def charge_missing(db: AsyncSession, outlet_id=None,
                          since: Optional[datetime] = None) -> dict:
    """Idempotently charge every order find_uncharged_completed finds.

    Flag-gated exactly like charge_if_eligible: a no-op while
    SERVICE_FEE_LEDGER_ENABLED is false. Each order is charged inside its
    OWN SAVEPOINT, so one order raising (a repeat of the same failure that
    produced the gap, say) rolls back only that attempt and the sweep
    continues with the rest rather than aborting the whole run.
    """
    if not settings.SERVICE_FEE_LEDGER_ENABLED:
        return {"charged": 0, "already_charged": 0, "failed": 0,
                "candidates": 0, "reason": "flag_off"}

    candidates = await find_uncharged_completed(db, outlet_id=outlet_id, since=since)
    charged = already_charged = failed = 0
    for c in candidates:
        try:
            async with db.begin_nested():
                result = await charge_if_eligible(db, c["order_id"], commit=False)
        except Exception:
            failed += 1
            logger.warning(
                "fee_ledger_sweep_charge_failed order_id=%s", c["order_id"])
            continue
        if result["charged"]:
            charged += 1
        elif result.get("reason") == "already_charged":
            already_charged += 1
        else:
            failed += 1
    await db.commit()
    return {"charged": charged, "already_charged": already_charged,
            "failed": failed, "candidates": len(candidates)}


async def verify_chain(db: AsyncSession, outlet_id) -> dict:
    """Wraps the SQL verify_chain(outlet_id) function. {"ok": True} when no
    broken row is found; otherwise the first broken row's id and reason."""
    row = (await db.execute(
        text("SELECT * FROM verify_chain(:outlet_id)"),
        {"outlet_id": str(outlet_id)},
    )).first()
    if row is None:
        return {"ok": True}
    return {"ok": False, "broken_id": str(row[0]), "reason": row[1]}
