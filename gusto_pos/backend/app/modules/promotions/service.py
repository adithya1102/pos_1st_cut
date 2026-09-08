"""Business logic for promotions (migration 016).

Raw `text()` throughout, matching AdminService and CarevoService: the new tables
are read and written by SQL only, so no existing ORM mapper changes and the app
stays importable whether or not migration 016 has been applied.

ONE service backs all three audiences (admin, owner, customer). The audience is
never inferred from the payload — the caller passes `scope` and, for owners, the
outlet id resolved from their own JWT. A request body cannot influence either.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.promotions.schema import benefit_text

CAMPAIGN = "CAREVO_CAMPAIGN"
OFFER = "RESTAURANT_OFFER"

# redemption_count is COUNTED from the ledger every read rather than cached on
# the promotion. A cached counter is one more thing that can disagree with the
# rows it summarises, and the counts here are tiny.
_SELECT_FULL = """
    SELECT p.id, p.code, p.label, p.scope, p.outlet_id,
           o.location_name AS outlet_name,
           p.discount_type, p.discount_value, p.max_discount_amount,
           p.min_order_value, p.creator_name, p.max_redemptions_total,
           p.max_redemptions_per_customer, p.is_active,
           p.created_by_user_id, p.created_at,
           (SELECT count(*) FROM promotion_redemptions r
             WHERE r.promotion_id = p.id) AS redemption_count
    FROM promotions p
    LEFT JOIN outlets o ON o.id = p.outlet_id
"""

# Columns a PATCH may write, per audience. Anything absent from these tuples
# cannot be changed by that caller no matter what the body contains — which is
# how `scope` and an owner's `outlet_id` stay immutable.
_CAMPAIGN_PATCHABLE = (
    "label", "code", "outlet_id", "discount_type", "discount_value",
    "max_discount_amount", "min_order_value", "creator_name",
    "max_redemptions_total", "max_redemptions_per_customer", "is_active",
)
_OFFER_PATCHABLE = (
    "label", "code", "discount_type", "discount_value", "max_discount_amount",
    "min_order_value", "max_redemptions_total",
    "max_redemptions_per_customer", "is_active",
)


class PromotionService:
    # ------------------------------ helpers --------------------------------
    @staticmethod
    def _row(r: Any) -> dict:
        return {
            "id": r.id,
            "code": r.code,
            "label": r.label,
            "scope": r.scope,
            "outlet_id": r.outlet_id,
            "outlet_name": r.outlet_name,
            "discount_type": r.discount_type,
            "discount_value": float(r.discount_value or 0),
            "max_discount_amount": (
                float(r.max_discount_amount)
                if r.max_discount_amount is not None else None
            ),
            "min_order_value": (
                float(r.min_order_value) if r.min_order_value is not None else None
            ),
            "creator_name": r.creator_name,
            "max_redemptions_total": r.max_redemptions_total,
            "max_redemptions_per_customer": r.max_redemptions_per_customer or 1,
            "is_active": bool(r.is_active),
            "created_by_user_id": r.created_by_user_id,
            "created_at": r.created_at,
            "redemption_count": int(r.redemption_count or 0),
            "benefit_text": benefit_text(
                r.discount_type,
                float(r.discount_value or 0),
                float(r.max_discount_amount) if r.max_discount_amount is not None else None,
                float(r.min_order_value) if r.min_order_value is not None else None,
            ),
        }

    @staticmethod
    def _guardrail(scope: str, discount_type: Optional[str],
                   max_discount_amount: Optional[float]) -> None:
        """Server-side enforcement of the percentage cap on Restaurant Offers.

        Second of three layers. The Pydantic validator catches a bad create
        body; this catches everything else — a PATCH that flips discount_type
        to PERCENT while leaving max_discount_amount NULL, or any future caller
        that bypasses the schema. The DB CHECK
        `promotions_percent_offer_requires_cap` is the last line.

        Evaluated against the MERGED row, never the payload alone: a patch
        sending only `{"discount_type": "PERCENT"}` is invalid precisely
        because of a value it does not contain.
        """
        if scope == OFFER and discount_type == "PERCENT" and max_discount_amount is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "A percentage offer needs a maximum discount — otherwise a "
                    "large order could take an unlimited amount off."
                ),
            )

    @staticmethod
    def _auto_label(discount_type: str, discount_value: float,
                    max_discount_amount: Optional[float],
                    min_order_value: Optional[float]) -> str:
        """Owners are never asked to write a label; it is derived from what they
        actually chose, so it cannot describe a different offer than the one
        that will be applied."""
        return benefit_text(
            discount_type, discount_value, max_discount_amount, min_order_value
        )

    # ------------------------------- reads ---------------------------------
    @staticmethod
    async def list_all(db: AsyncSession, *, scope: Optional[str] = None,
                       outlet_id: Optional[uuid.UUID] = None) -> list[dict]:
        """Admin list (scope=CAREVO_CAMPAIGN) or owner list (outlet-scoped)."""
        rows = (await db.execute(text(
            _SELECT_FULL +
            " WHERE (CAST(:scope AS varchar) IS NULL OR p.scope = CAST(:scope AS varchar))"
            "   AND (CAST(:oid AS uuid) IS NULL OR p.outlet_id = CAST(:oid AS uuid))"
            " ORDER BY p.is_active DESC, p.created_at DESC"
        ), {"scope": scope, "oid": str(outlet_id) if outlet_id else None})).fetchall()
        return [PromotionService._row(r) for r in rows]

    @staticmethod
    async def get_one(db: AsyncSession, promotion_id: uuid.UUID, *,
                      scope: Optional[str] = None,
                      outlet_id: Optional[uuid.UUID] = None) -> dict:
        """Fetch with the caller's scope/outlet folded into the WHERE clause.

        Not "fetch then compare": a row the caller may not touch returns 404
        from the query itself, so there is no branch that could forget the check.
        """
        row = (await db.execute(text(
            _SELECT_FULL +
            " WHERE p.id = :pid"
            "   AND (CAST(:scope AS varchar) IS NULL OR p.scope = CAST(:scope AS varchar))"
            "   AND (CAST(:oid AS uuid) IS NULL OR p.outlet_id = CAST(:oid AS uuid))"
        ), {"pid": str(promotion_id), "scope": scope,
            "oid": str(outlet_id) if outlet_id else None})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Promotion not found")
        return PromotionService._row(row)

    @staticmethod
    async def list_for_customer(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        """Everything a customer can use at this outlet, in one list.

        Three sources, deliberately merged rather than shown as separate
        sections: platform-wide CareVo Campaigns (outlet_id IS NULL), Campaigns
        targeted at this outlet, and this outlet's own Restaurant Offers. The
        customer does not care who funds it.

        Exhausted promotions are filtered out here as well as rejected at
        checkout — surfacing an offer that is guaranteed to fail is worse than
        not surfacing it.
        """
        rows = (await db.execute(text(
            _SELECT_FULL +
            """
             WHERE p.is_active = true
               AND (p.outlet_id IS NULL OR p.outlet_id = :oid)
               AND (
                     p.max_redemptions_total IS NULL
                     OR (SELECT count(*) FROM promotion_redemptions r
                          WHERE r.promotion_id = p.id) < p.max_redemptions_total
                   )
             ORDER BY (p.outlet_id IS NULL), p.created_at DESC
            """
        ), {"oid": str(outlet_id)})).fetchall()
        return [PromotionService._row(r) for r in rows]

    @staticmethod
    async def offer_summary_by_outlet(db: AsyncSession) -> dict[str, dict]:
        """{outlet_id: {"count": n, "text": "..."}} for the discovery list chip.

        ONE query for the whole outlet list rather than one per card. Platform-
        wide campaigns (outlet_id IS NULL) apply to EVERY outlet, so they are
        merged into every entry — including outlets that have no offer of their
        own, which is why the caller must ask for keys it did not expect.

        Best-effort by contract: returns {} rather than raising if the
        promotions tables are absent. The restaurant list must keep working on a
        deploy where migration 016 has not been applied yet.
        """
        try:
            rows = (await db.execute(text("""
                SELECT p.outlet_id, p.discount_type, p.discount_value,
                       p.max_discount_amount, p.min_order_value
                FROM promotions p
                WHERE p.is_active = true
                  AND (
                        p.max_redemptions_total IS NULL
                        OR (SELECT count(*) FROM promotion_redemptions r
                             WHERE r.promotion_id = p.id) < p.max_redemptions_total
                      )
                ORDER BY p.created_at DESC
            """))).fetchall()
        except Exception:
            await db.rollback()
            return {}

        def _text(r: Any) -> str:
            return benefit_text(
                r.discount_type, float(r.discount_value or 0),
                float(r.max_discount_amount) if r.max_discount_amount is not None else None,
                float(r.min_order_value) if r.min_order_value is not None else None,
            )

        by_outlet: dict[str, dict] = {}
        platform = [r for r in rows if r.outlet_id is None]
        for r in rows:
            if r.outlet_id is None:
                continue
            slot = by_outlet.setdefault(str(r.outlet_id), {"count": 0, "text": None})
            slot["count"] += 1
            # First row wins the headline; rows arrive newest-first.
            slot["text"] = slot["text"] or _text(r)

        if platform:
            # Applies to outlets with no offer of their own too, so seed those.
            for slot in by_outlet.values():
                slot["count"] += len(platform)
            by_outlet.setdefault("*", {"count": len(platform), "text": _text(platform[0])})
        return by_outlet

    # ------------------------------- writes --------------------------------
    @staticmethod
    async def create(db: AsyncSession, payload, *, scope: str,
                     created_by_user_id: Optional[uuid.UUID],
                     outlet_id: Optional[uuid.UUID]) -> dict:
        """Insert one promotion. `scope` and `outlet_id` come from the ENDPOINT,
        never from `payload` — see the module docstring."""
        data = payload.model_dump(exclude_unset=True)

        discount_type = data.get("discount_type")
        max_discount = data.get("max_discount_amount")
        PromotionService._guardrail(scope, discount_type, max_discount)

        label = (data.get("label") or "").strip() or PromotionService._auto_label(
            discount_type, float(data["discount_value"]),
            max_discount, data.get("min_order_value"),
        )

        params = {
            "code": data.get("code"),
            "label": label,
            "scope": scope,
            "outlet_id": str(outlet_id) if outlet_id else None,
            "discount_type": discount_type,
            "discount_value": data["discount_value"],
            "max_discount_amount": max_discount,
            "min_order_value": data.get("min_order_value"),
            # Enforced by the DB CHECK too; passing it for a Restaurant Offer
            # would be rejected rather than silently dropped.
            "creator_name": (data.get("creator_name") or None) if scope == CAMPAIGN else None,
            "max_redemptions_total": data.get("max_redemptions_total"),
            "max_redemptions_per_customer": data.get("max_redemptions_per_customer") or 1,
            "is_active": bool(data.get("is_active", False)),
            "created_by": str(created_by_user_id) if created_by_user_id else None,
        }

        try:
            row = (await db.execute(text("""
                INSERT INTO promotions
                    (code, label, scope, outlet_id, discount_type, discount_value,
                     max_discount_amount, min_order_value, creator_name,
                     max_redemptions_total, max_redemptions_per_customer,
                     is_active, created_by_user_id)
                VALUES
                    (:code, :label, :scope, CAST(:outlet_id AS uuid), :discount_type,
                     :discount_value, :max_discount_amount, :min_order_value,
                     :creator_name, :max_redemptions_total,
                     :max_redemptions_per_customer, :is_active,
                     CAST(:created_by AS uuid))
                RETURNING id
            """), params)).first()
        except IntegrityError as exc:
            await db.rollback()
            raise PromotionService._integrity_error(exc)

        return {"id": row[0]}

    @staticmethod
    async def update(db: AsyncSession, promotion_id: uuid.UUID, payload, *,
                     scope: str, outlet_id: Optional[uuid.UUID]) -> None:
        """Partial update, guarded by scope (+ outlet, for owners).

        Reads the current row first so the guardrail can be judged against the
        merged result, then writes only the fields actually sent.
        """
        current = await PromotionService.get_one(
            db, promotion_id, scope=scope, outlet_id=outlet_id
        )
        data = payload.model_dump(exclude_unset=True)

        allowed = _CAMPAIGN_PATCHABLE if scope == CAMPAIGN else _OFFER_PATCHABLE
        changes = {k: v for k, v in data.items() if k in allowed}
        if not changes:
            return

        merged = {**current, **changes}
        PromotionService._guardrail(
            scope, merged.get("discount_type"), merged.get("max_discount_amount")
        )
        if (
            merged.get("discount_type") == "PERCENT"
            and merged.get("discount_value") is not None
            and float(merged["discount_value"]) > 100
        ):
            raise HTTPException(
                status_code=422, detail="A percentage discount cannot exceed 100%."
            )

        sets, params = [], {"pid": str(promotion_id)}
        for key, value in changes.items():
            if key == "outlet_id":
                sets.append("outlet_id = CAST(:outlet_id AS uuid)")
                params["outlet_id"] = str(value) if value else None
            else:
                sets.append(f"{key} = :{key}")
                params[key] = value

        try:
            await db.execute(text(
                f"UPDATE promotions SET {', '.join(sets)} WHERE id = :pid"
            ), params)
        except IntegrityError as exc:
            await db.rollback()
            raise PromotionService._integrity_error(exc)

    @staticmethod
    def _integrity_error(exc: IntegrityError) -> HTTPException:
        """Turn a constraint violation into something the UI can show.

        The CHECK names are the contract here — matching on them rather than on
        driver text keeps the mapping stable across SQLAlchemy/asyncpg versions.
        """
        msg = str(getattr(exc, "orig", exc))
        if "idx_promotions_code_upper" in msg:
            return HTTPException(status_code=409, detail="That code is already in use.")
        if "promotions_percent_offer_requires_cap" in msg:
            return HTTPException(
                status_code=422,
                detail="A percentage offer needs a maximum discount.",
            )
        if "promotions_offer_requires_outlet" in msg:
            return HTTPException(
                status_code=422, detail="A restaurant offer must belong to an outlet."
            )
        if "promotions_creator_is_campaign_only" in msg:
            return HTTPException(
                status_code=422,
                detail="Creator attribution is only available on CareVo campaigns.",
            )
        return HTTPException(status_code=422, detail="Could not save the promotion.")

    # -------------------------- checkout application ------------------------
    @staticmethod
    async def apply_to_order(
        db: AsyncSession, *, customer_id: uuid.UUID, outlet_id: uuid.UUID,
        order_id: uuid.UUID, gross: float,
        promotion_id: Optional[uuid.UUID] = None, code: Optional[str] = None,
    ) -> dict:
        """Validate + record one promotion against an order. Returns the applied
        discount; raises 4xx with a customer-readable reason otherwise.

        Runs INSIDE create_order's open transaction. Nothing is committed here,
        so any later failure in create_order rolls the redemption back with it
        and the promotion stays claimable — the same discipline
        _consume_points_coupon follows for coupons.

        Messages are specific (unlike the deliberately-uniform coupon error),
        because promotions are publicly listed: there is no code to probe for
        and "you already used this" is genuinely the useful thing to say.
        """
        if promotion_id is not None:
            row = (await db.execute(text(
                "SELECT * FROM promotions WHERE id = :pid"
            ), {"pid": str(promotion_id)})).first()
        else:
            row = (await db.execute(text(
                "SELECT * FROM promotions WHERE upper(code) = upper(:code)"
            ), {"code": (code or "").strip()})).first()

        if row is None or not row.is_active:
            raise HTTPException(
                status_code=422, detail="That offer is not available."
            )

        # A targeted campaign or a restaurant offer only applies at its outlet.
        # Platform-wide campaigns (outlet_id IS NULL) apply everywhere.
        if row.outlet_id is not None and str(row.outlet_id) != str(outlet_id):
            raise HTTPException(
                status_code=422,
                detail="That offer isn't valid at this restaurant.",
            )

        min_order = float(row.min_order_value or 0)
        if min_order and gross < min_order:
            raise HTTPException(
                status_code=422,
                detail="Add ₹{:g} more to use this offer (minimum ₹{:g}).".format(
                    round(min_order - gross, 2), min_order
                ),
            )

        if row.max_redemptions_total is not None:
            used = (await db.execute(text(
                "SELECT count(*) FROM promotion_redemptions WHERE promotion_id = :pid"
            ), {"pid": str(row.id)})).scalar() or 0
            if int(used) >= int(row.max_redemptions_total):
                raise HTTPException(
                    status_code=422, detail="This offer has been fully claimed."
                )

        cap = int(row.max_redemptions_per_customer or 1)
        mine = (await db.execute(text(
            "SELECT count(*) FROM promotion_redemptions "
            "WHERE promotion_id = :pid AND customer_id = :cid"
        ), {"pid": str(row.id), "cid": str(customer_id)})).scalar() or 0
        if int(mine) >= cap:
            raise HTTPException(
                status_code=422,
                detail=("You've already used this offer." if cap == 1
                        else "You've used this offer the maximum number of times."),
            )

        discount = PromotionService.compute_discount(
            gross,
            row.discount_type,
            float(row.discount_value or 0),
            float(row.max_discount_amount) if row.max_discount_amount is not None else None,
        )

        try:
            await db.execute(text("""
                INSERT INTO promotion_redemptions
                    (promotion_id, customer_id, order_id, discount_amount,
                     per_customer_cap)
                VALUES (:pid, :cid, :oid, :amt, :cap)
            """), {"pid": str(row.id), "cid": str(customer_id),
                   "oid": str(order_id), "amt": discount, "cap": cap})
        except IntegrityError:
            # Both unique indexes land here: a second promotion on one order,
            # or a concurrent second redemption by the same customer that the
            # count above could not see. The count is the friendly path; this
            # is the one that actually holds under concurrency.
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="That offer could not be applied to this order.",
            )

        await db.execute(text(
            "UPDATE customer_orders SET promotion_id = :pid WHERE id = :oid"
        ), {"pid": str(row.id), "oid": str(order_id)})

        return {
            "promotion_id": row.id,
            "label": row.label,
            "discount_amount": discount,
        }

    @staticmethod
    def compute_discount(gross: float, discount_type: str, discount_value: float,
                         max_discount_amount: Optional[float]) -> float:
        """Rupees off, capped twice: by max_discount_amount, then by the basket.

        The second clamp matters — a ₹100 flat offer on an ₹80 basket takes ₹80,
        never ₹100, so the order can never settle below zero and the recorded
        discount is never larger than what was actually given.
        """
        if discount_type == "PERCENT":
            amount = gross * (discount_value / 100.0)
            if max_discount_amount is not None:
                amount = min(amount, max_discount_amount)
        else:
            amount = discount_value
        return round(min(max(amount, 0.0), gross), 2)
