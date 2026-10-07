"""Stock reservation (migration 033).

An item with `menu_items.stock_remaining IS NULL` is UNTRACKED and nothing here
touches it — which is every item until a restaurant sets a number, so this
module is inert on deploy exactly like the acceptance one.

WHAT WAS WRONG WITHOUT IT
-------------------------
There was no stock concept on the customer path at all. The only gate was
`is_available AND is_active`, a boolean with nothing behind it, so two
customers ordering the last portion both succeeded — nothing was ever
decremented. `inventory.current_stock` and `products.stock_qty` exist but
belong to legacy staff-gated POS modules, hold zero rows, and no customer-path
code reads them.

THE CONCURRENCY RULE
--------------------
    UPDATE menu_items SET stock_remaining = stock_remaining - :q
     WHERE id = :id AND stock_remaining >= :q

The WHERE clause is the whole mechanism. PostgreSQL serialises writes to a
row, so of N racing transactions exactly one at a time re-evaluates
`stock_remaining >= :q` against the committed value; the ones that find it
insufficient match zero rows and are refused. No SELECT ... FOR UPDATE, no
advisory lock, no SERIALIZABLE. The CHECK (stock_remaining >= 0) added by the
migration is the backstop that turns a future weakening of that predicate into
an error instead of negative stock.

DEADLOCK AVOIDANCE
------------------
Rows are locked in ASCENDING menu_item_id ORDER, always. Two carts containing
the same two dishes in opposite orders would otherwise be able to take one row
each and then wait on the other forever. Sorting by a total order on the
primary key means every transaction in the system acquires these locks in the
same sequence, which makes a cycle impossible.

WHY A RESERVATIONS TABLE AND NOT JUST THE DECREMENT
---------------------------------------------------
The decrement alone cannot answer "give it back". An order abandoned unpaid,
rejected, acceptance-expired or whose payment failed must return its units, and
computing that from the order's line items would double-release on a retry. A
row per (order, item) with an explicit HELD/COMMITTED/RELEASED state makes
release idempotent: you can only release what is still HELD.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

HELD = "HELD"
COMMITTED = "COMMITTED"
RELEASED = "RELEASED"


def _utcnow() -> datetime:
    """AWARE UTC — expires_at is timestamptz; see model._utcnow for why naive
    values are a real bug here and not a style preference."""
    return datetime.now(timezone.utc)


class StockService:
    # ------------------------------ reserve --------------------------------
    @staticmethod
    async def reserve_for_order(db: AsyncSession, order_id, items) -> list[dict]:
        """Hold stock for one order's TRACKED items. Caller's transaction, no commit.

        `items` is any iterable of objects with `.menu_item_id` and `.quantity`.
        Quantities for the same dish are SUMMED first — two lines of the same
        item are one hold of the total, which is both what the customer is
        buying and what the (order_id, menu_item_id) unique index requires.

        Called at ORDER CREATION, before payment, deliberately. Reserving at
        payment instead would mean a customer can complete checkout for a dish
        that sold out while they were typing, which is the worse failure: they
        have been charged. The cost is that an abandoned unpaid order holds
        units for STOCK_RESERVATION_TTL_MINUTES, which the sweeper reclaims.

        THE CART NEVER RESERVES. /customer/cart/check is a read — it reports
        what is available and holds nothing. A cart that reserved would let any
        anonymous browser empty a restaurant's stock without placing an order.

        Raises 409 ITEM_SOLD_OUT, naming the item and how many are actually
        left, as soon as one item cannot be satisfied. The caller's transaction
        rolls back, so partial holds are impossible.
        """
        wanted: dict[str, int] = {}
        for line in items:
            key = str(line.menu_item_id)
            wanted[key] = wanted.get(key, 0) + int(line.quantity)
        if not wanted:
            return []

        # Which of these are tracked at all. Untracked (NULL) items are skipped
        # entirely — no reservation row, no decrement, no 409.
        rows = (await db.execute(text("""
            SELECT id, name, stock_remaining
              FROM menu_items
             WHERE id = ANY(:ids) AND stock_remaining IS NOT NULL
             ORDER BY id
        """), {"ids": list(wanted.keys())})).fetchall()
        if not rows:
            return []

        expires_at = _utcnow() + timedelta(
            minutes=settings.STOCK_RESERVATION_TTL_MINUTES)

        held: list[dict] = []
        # ASCENDING id order — see the module docstring. The ORDER BY above is
        # what provides it, and iterating the query result preserves it.
        for r in rows:
            qty = wanted[str(r.id)]
            res = await db.execute(text("""
                UPDATE menu_items
                   SET stock_remaining = stock_remaining - :q
                 WHERE id = :id AND stock_remaining >= :q
                RETURNING stock_remaining
            """), {"q": qty, "id": str(r.id)})
            row = res.first()
            if row is None:
                # Re-read rather than reporting the value from the SELECT
                # above: by now another transaction may have taken more, and
                # telling the customer a stale number is worse than telling
                # them none.
                remaining = await db.scalar(text(
                    "SELECT stock_remaining FROM menu_items WHERE id = :id"),
                    {"id": str(r.id)})
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "ITEM_SOLD_OUT",
                        "menu_item_id": str(r.id),
                        "name": r.name,
                        "requested": qty,
                        "remaining": int(remaining or 0),
                        "message": (
                            f"{r.name}: only {int(remaining or 0)} left, "
                            f"you asked for {qty}."
                        ),
                    },
                )

            await db.execute(text("""
                INSERT INTO stock_reservations
                    (id, order_id, menu_item_id, qty, state, expires_at,
                     created_at, updated_at)
                VALUES (gen_random_uuid(), :oid, :iid, :q, :st, :exp,
                        now(), now())
                ON CONFLICT (order_id, menu_item_id)
                DO UPDATE SET qty = EXCLUDED.qty, state = EXCLUDED.state,
                              expires_at = EXCLUDED.expires_at,
                              updated_at = now()
            """), {"oid": str(order_id), "iid": str(r.id), "q": qty,
                   "st": HELD, "exp": expires_at})

            remaining_now = int(row[0])
            held.append({"menu_item_id": str(r.id), "qty": qty,
                         "remaining": remaining_now})

            # At zero, stop offering it. is_available is the EXISTING customer
            # -facing gate, so flipping it here means the menu hides the dish
            # through the path it already uses rather than needing every reader
            # to learn about stock.
            if remaining_now == 0:
                await db.execute(text(
                    "UPDATE menu_items SET is_available = false WHERE id = :id"),
                    {"id": str(r.id)})
        return held

    # --------------------------- commit / release --------------------------
    @staticmethod
    async def commit_for_order(db: AsyncSession, order_id) -> int:
        """HELD -> COMMITTED. The units are spent. Caller's transaction.

        Guarded on state = HELD so a replayed webhook cannot move a RELEASED
        reservation to COMMITTED and silently consume stock that was already
        given back.
        """
        res = await db.execute(text("""
            UPDATE stock_reservations SET state = :new, updated_at = now()
             WHERE order_id = :oid AND state = :old
        """), {"new": COMMITTED, "old": HELD, "oid": str(order_id)})
        return res.rowcount or 0

    @staticmethod
    async def release_for_order(db: AsyncSession, order_id, *, reason: str) -> int:
        """HELD -> RELEASED, returning the units. Caller's transaction.

        ONLY touches HELD rows, which is what makes this idempotent and safe to
        call from every terminal path (cancel, reject, acceptance expiry, TTL
        abandon, payment failure) without any of them having to know whether
        another already ran. A COMMITTED reservation is never released by this
        — the food was made.
        """
        rows = (await db.execute(text("""
            UPDATE stock_reservations SET state = :new, updated_at = now()
             WHERE order_id = :oid AND state = :old
            RETURNING menu_item_id, qty
        """), {"new": RELEASED, "old": HELD, "oid": str(order_id)})).fetchall()
        if not rows:
            return 0

        for r in sorted(rows, key=lambda x: str(x.menu_item_id)):
            await db.execute(text("""
                UPDATE menu_items
                   SET stock_remaining = stock_remaining + :q,
                       -- Coming back from zero makes the dish orderable again.
                       -- Only when it was actually at zero: an item a human
                       -- switched off for the day must stay off.
                       is_available = CASE WHEN stock_remaining = 0 THEN true
                                           ELSE is_available END
                 WHERE id = :id AND stock_remaining IS NOT NULL
            """), {"q": int(r.qty), "id": str(r.menu_item_id)})
        logger.info("released %s stock reservation(s) for order %s (%s)",
                    len(rows), order_id, reason)
        return len(rows)

    @staticmethod
    async def rereserve_for_order(db: AsyncSession, order_id) -> bool:
        """Re-take a hold that was already RELEASED. Caller's transaction.

        For the late-webhook case: the sweeper (or a cancel) gave the units
        back, and then the payment actually landed. The money is real, so the
        order has to either get its stock back or be cancelled and refunded —
        silently proceeding would promise food the restaurant does not have.

        Returns True when every released row was re-taken. False means at least
        one could not be, and the caller is expected to cancel + flag a refund.
        Ascending id order, same as reserve_for_order.
        """
        rows = (await db.execute(text("""
            SELECT menu_item_id, qty FROM stock_reservations
             WHERE order_id = :oid AND state = :st
             ORDER BY menu_item_id
        """), {"oid": str(order_id), "st": RELEASED})).fetchall()
        if not rows:
            return True

        for r in rows:
            res = await db.execute(text("""
                UPDATE menu_items
                   SET stock_remaining = stock_remaining - :q
                 WHERE id = :id AND stock_remaining >= :q
                RETURNING stock_remaining
            """), {"q": int(r.qty), "id": str(r.menu_item_id)})
            got = res.first()
            if got is None:
                logger.warning(
                    "re-reservation failed for order %s item %s qty %s — "
                    "stock was given back and is now gone",
                    order_id, r.menu_item_id, r.qty)
                return False
            await db.execute(text("""
                UPDATE stock_reservations
                   SET state = :new, updated_at = now()
                 WHERE order_id = :oid AND menu_item_id = :iid
            """), {"new": HELD, "oid": str(order_id),
                   "iid": str(r.menu_item_id)})
            if int(got[0]) == 0:
                await db.execute(text(
                    "UPDATE menu_items SET is_available = false WHERE id = :id"),
                    {"id": str(r.menu_item_id)})
        return True

    # ------------------------------ sweeper --------------------------------
    @staticmethod
    async def sweep_expired(db: AsyncSession, *, outlet_id=None) -> int:
        """Reclaim HELD reservations on UNPAID orders past their expiry.

        WHY THIS IS NOT COVERED BY THE 45-MINUTE PICKUP TTL:
        _expire_stale_pickups selects `status = ANY(_LIVE_STATUSES)` and
        _LIVE_STATUSES is {PAID, RECEIVED, PREPARING, READY}. An unpaid order
        is CREATED, so that sweeper never touches it — there is no expiry for
        unpaid orders anywhere in the codebase. Without this, one abandoned
        checkout would hold the last portion of a dish until the process
        restarted.

        Scoped to UNPAID orders only. A PAID order's hold is the restaurant's
        commitment and is released by a terminal transition, never by a clock.

        Check-on-read, like every other sweeper here: called from order
        creation (so the stock you are about to reserve against is current) and
        from the owner queue poll.
        """
        clauses = ["sr.state = :st", "sr.expires_at <= now()",
                   "co.payment_status <> 'PAID'"]
        params: dict = {"st": HELD}
        if outlet_id is not None:
            clauses.append("co.outlet_id = :oid")
            params["oid"] = str(outlet_id)

        rows = (await db.execute(text(f"""
            UPDATE stock_reservations sr
               SET state = :rel, updated_at = now()
              FROM customer_orders co
             WHERE co.id = sr.order_id AND {' AND '.join(clauses)}
            RETURNING sr.menu_item_id, sr.qty, sr.order_id
        """), {**params, "rel": RELEASED})).fetchall()
        if not rows:
            return 0

        for r in sorted(rows, key=lambda x: str(x.menu_item_id)):
            await db.execute(text("""
                UPDATE menu_items
                   SET stock_remaining = stock_remaining + :q,
                       is_available = CASE WHEN stock_remaining = 0 THEN true
                                           ELSE is_available END
                 WHERE id = :id AND stock_remaining IS NOT NULL
            """), {"q": int(r.qty), "id": str(r.menu_item_id)})
        await db.commit()
        logger.info("swept %s expired stock reservation(s)", len(rows))
        return len(rows)

    # ---------------------------- owner control ----------------------------
    @staticmethod
    async def set_stock(db: AsyncSession, item_id, outlet_id,
                        quantity: int | None) -> dict:
        """Set or clear an item's tracked stock. Outlet-scoped.

        `quantity=None` means UNTRACKED — the item reverts to today's
        behaviour of unlimited availability, which is the escape hatch for a
        restaurant that turned counting on and regretted it.

        Setting a positive number on an item that had sold out ALSO flips
        is_available back on, because "there are 5 again" and "it is orderable"
        are the same statement from the restaurant's point of view, and making
        them two separate taps is how a dish stays hidden with stock sitting
        behind it.
        """
        if quantity is not None and quantity < 0:
            raise HTTPException(status_code=422,
                                detail="quantity must be >= 0 or null")

        # CAST(:q AS integer) throughout, and it is required rather than
        # decorative: the parameter appears in an IS NULL test and in >/=
        # comparisons, and asyncpg refuses to infer a type from that
        # ("could not determine data type of parameter $1").
        row = (await db.execute(text("""
            UPDATE menu_items mi
               SET stock_remaining = CAST(:q AS integer),
                   is_available = CASE
                       WHEN CAST(:q AS integer) IS NULL THEN mi.is_available
                       WHEN CAST(:q AS integer) > 0
                            AND COALESCE(mi.stock_remaining, 0) = 0 THEN true
                       WHEN CAST(:q AS integer) = 0 THEN false
                       ELSE mi.is_available END
              FROM categories c, menus m
             WHERE mi.id = :iid
               AND mi.category_id = c.id AND c.menu_id = m.id
               AND m.outlet_id = :oid
            RETURNING mi.id, mi.name, mi.stock_remaining, mi.is_available
        """), {"q": quantity, "iid": str(item_id), "oid": str(outlet_id)})).first()
        if row is None:
            raise HTTPException(status_code=404,
                                detail="Menu item not found for this outlet")
        await db.commit()
        return {"id": row[0], "name": row[1], "stock_remaining": row[2],
                "is_available": bool(row[3])}
