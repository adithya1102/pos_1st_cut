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

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

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
