"""Pydantic v2 schemas for promotions (migration 016).

Two audiences, deliberately two different input shapes:

* CareVo Campaigns (admin) expose every knob, including targeting and creator
  attribution.
* Restaurant Offers (owner) expose the smallest set an owner can reason about.
  `scope` and `outlet_id` are absent from the owner input ON PURPOSE — they are
  not "defaulted", they are not accepted at all, so no owner request can carry
  a scope or an outlet other than their own.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Scope = Literal["CAREVO_CAMPAIGN", "RESTAURANT_OFFER"]
DiscountType = Literal["PERCENT", "FLAT"]

# Same unambiguous alphabet family as _make_coupon_code, plus a hyphen so
# hand-written codes like SUMMER-20 are allowed. Rejected here rather than at
# the DB so the owner gets a readable message instead of a constraint error.
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{2,23}$")


def _clean_code(value: Optional[str]) -> Optional[str]:
    """Normalise to upper-case, or None. Blank input means "no code"."""
    if value is None:
        return None
    code = value.strip().upper()
    if not code:
        return None
    if not _CODE_RE.match(code):
        raise ValueError(
            "Code must be 3-24 characters: letters, numbers and hyphens only."
        )
    return code


def benefit_text(
    discount_type: str,
    discount_value: float,
    max_discount_amount: Optional[float],
    min_order_value: Optional[float],
) -> str:
    """The one-line customer-facing benefit, derived — never stored twice.

    Built here (not in the app) so the outlet chip, the offers list and the
    owner's own preview cannot word the same offer three different ways.
    """
    if discount_type == "PERCENT":
        head = "{:g}% off".format(discount_value)
        if max_discount_amount:
            head += " up to ₹{:g}".format(max_discount_amount)
    else:
        head = "₹{:g} off".format(discount_value)
    if min_order_value:
        head += " on orders above ₹{:g}".format(min_order_value)
    return head


class _PromotionFields(BaseModel):
    """Fields shared by every create/update input, with the shared validation."""

    label: Optional[str] = Field(default=None, max_length=120)
    code: Optional[str] = Field(default=None, max_length=24)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[float] = Field(default=None, gt=0)
    max_discount_amount: Optional[float] = Field(default=None, gt=0)
    min_order_value: Optional[float] = Field(default=None, ge=0)
    max_redemptions_total: Optional[int] = Field(default=None, ge=1)
    max_redemptions_per_customer: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None

    @field_validator("code")
    @classmethod
    def _code(cls, v: Optional[str]) -> Optional[str]:
        return _clean_code(v)

    @model_validator(mode="after")
    def _percent_within_100(self):
        if (
            self.discount_type == "PERCENT"
            and self.discount_value is not None
            and self.discount_value > 100
        ):
            raise ValueError("A percentage discount cannot exceed 100%.")
        return self


# ------------------------- CareVo Campaign (admin) ---------------------------
class CampaignCreateIn(_PromotionFields):
    label: str = Field(..., min_length=2, max_length=120)
    discount_type: DiscountType
    discount_value: float = Field(..., gt=0)
    # NULL = platform-wide. Set = campaign targeted at one restaurant. CareVo
    # funds it either way; targeting only decides where it surfaces.
    outlet_id: Optional[uuid.UUID] = None
    creator_name: Optional[str] = Field(default=None, max_length=80)
    max_redemptions_per_customer: int = Field(default=1, ge=1)
    is_active: bool = False


class CampaignUpdateIn(_PromotionFields):
    """Every field optional — only what is sent is written."""

    outlet_id: Optional[uuid.UUID] = None
    creator_name: Optional[str] = Field(default=None, max_length=80)


# ------------------------ Restaurant Offer (owner) ---------------------------
class OfferCreateIn(_PromotionFields):
    """What the owner fills in. Note what is NOT here: scope, outlet_id,
    creator_name. Those are decided by the endpoint, not by the request body."""

    discount_type: DiscountType
    discount_value: float = Field(..., gt=0)
    # Optional: blank means the offer is auto-surfaced on the outlet card with
    # no code to type. Owners are never asked to invent one.
    code: Optional[str] = Field(default=None, max_length=24)
    max_redemptions_per_customer: int = Field(default=1, ge=1)
    is_active: bool = False

    @model_validator(mode="after")
    def _percent_needs_cap(self):
        """THE guardrail, first of three layers (API -> service -> CHECK).

        An uncapped "50% off" is how an owner accidentally hands ₹2000 to one
        large party order. A percentage Restaurant Offer must state its ceiling.
        """
        if self.discount_type == "PERCENT" and self.max_discount_amount is None:
            raise ValueError(
                "A percentage offer needs a maximum discount — "
                "otherwise a large order could take an unlimited amount off."
            )
        return self


class OfferUpdateIn(_PromotionFields):
    """Partial update. The percent-needs-a-cap guardrail is re-checked in the
    service against the MERGED row, because a patch that only flips
    discount_type to PERCENT is invalid too and cannot be judged from the
    payload alone."""


# --------------------------------- outputs -----------------------------------
class PromotionOut(BaseModel):
    """Full row. Used by both admin and owner reads; the owner simply never
    sees rows outside their own outlet."""

    id: uuid.UUID
    code: Optional[str] = None
    label: str
    scope: Scope
    outlet_id: Optional[uuid.UUID] = None
    outlet_name: Optional[str] = None
    discount_type: DiscountType
    discount_value: float
    max_discount_amount: Optional[float] = None
    min_order_value: Optional[float] = None
    creator_name: Optional[str] = None
    max_redemptions_total: Optional[int] = None
    max_redemptions_per_customer: int = 1
    is_active: bool = False
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    # V1 analytics: a count, nothing more. No per-day series, no revenue
    # attribution — those need a decision about what a "campaign-driven order"
    # is, which this release does not make.
    redemption_count: int = 0
    benefit_text: str = ""


class CustomerOfferOut(BaseModel):
    """What the customer app sees. Caps, funding and creator attribution are
    omitted — none of it changes what the customer gets."""

    id: uuid.UUID
    label: str
    benefit_text: str
    # Present so the app can show "CareVo" vs the restaurant's own badge.
    scope: Scope
    code: Optional[str] = None
    discount_type: DiscountType
    discount_value: float
    max_discount_amount: Optional[float] = None
    min_order_value: Optional[float] = None
    creator_name: Optional[str] = None


class DeletePromotionOut(BaseModel):
    id: uuid.UUID
    deleted: bool
