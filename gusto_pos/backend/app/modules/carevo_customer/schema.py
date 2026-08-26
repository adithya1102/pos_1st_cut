"""Pydantic v2 schemas for CareVo Skip customer + payment flows."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


# ----------------------------- Auth -----------------------------------------
class RequestOtpIn(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)


class RequestOtpOut(BaseModel):
    request_id: str
    stub: bool = True


class VerifyOtpIn(BaseModel):
    phone_number: str = Field(..., min_length=6, max_length=20)
    otp: str


class FirebaseAuthIn(BaseModel):
    """Real phone-auth exchange: a Firebase ID token for a CareVo session token.

    The phone number is read from the verified token's claims, never from the
    client — a client-supplied number here would be trivially forgeable.
    """
    id_token: str = Field(..., min_length=16)


class GoogleAuthIn(BaseModel):
    """Google sign-in exchange: a Firebase Google-provider ID token for a CareVo
    session token.

    Same rule as [FirebaseAuthIn] — email and uid are read from the verified
    token's claims, never from the client.
    """
    id_token: str = Field(..., min_length=16)


class CustomerPublic(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    # Optional since Google sign-in: a standalone Google identity has no
    # verified phone until the customer verifies one separately.
    phone_number: Optional[str] = None
    email: Optional[str] = None


class VerifyOtpOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer: CustomerPublic
    # True when this exchange CREATED the customer row — i.e. a signup rather
    # than a sign-in.
    #
    # The app needs it to decide whether a name typed at sign-in may replace
    # `customer.name`. On a new Google row that name arrived from the Google
    # profile seconds ago and should lose to what the customer typed; on an
    # existing row it may be one they deliberately set, and must win. The two
    # are indistinguishable from the response body alone.
    #
    # Defaults False so any caller that does not set it keeps the old,
    # conservative "never overwrite" behaviour.
    is_new_account: bool = False


# --------------------------- Discovery --------------------------------------
class OutletOut(BaseModel):
    id: uuid.UUID
    name: str
    address: Optional[str] = None
    is_open: bool = True
    distance_km: Optional[float] = None
    # When this outlet joined. Backs the app's "Newest" sort; Optional because
    # the column is nullable on rows that predate the current schema.
    created_at: Optional[datetime] = None
    upi_id: Optional[str] = None
    # Area within the city (migration 012). Null for outlets that predate it —
    # the app then renders the name alone rather than a dangling separator.
    locality: Optional[str] = None
    # Outlet contact number (migration 009), so the app can offer a direct call.
    # NULL for most outlets today — 5 of the 6 customer-visible ones in prod
    # have none — so the app HIDES the call action rather than rendering a
    # button that cannot dial. Absence is the common case, not an edge case.
    phone_number: Optional[str] = None
    # Outlet coordinates, so the app can hand off to Google Maps without an API
    # key or a geocoding round trip. Null for outlets that never captured a pin;
    # the app hides the Maps button in that case rather than linking to nowhere.
    #
    # Floats, not Decimal: these are consumed as a URL query string, and the
    # column is `numeric` which Pydantic would otherwise serialise as a string.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Storefront photo (migration 011). Null -> the app renders its fallback glyph.
    image_url: Optional[str] = None
    # Offer summary (migration 016) so the discovery card can show its inline
    # chip without one extra request per outlet. Counts this outlet's active
    # Restaurant Offers plus every active CareVo Campaign that reaches it;
    # offer_text is the headline benefit of the newest of those. 0/null means
    # the card renders exactly as it did before.
    offer_count: int = 0
    offer_text: Optional[str] = None


# ------------------------------ Menu ----------------------------------------
class MenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    base_price: float
    is_veg: bool
    is_available: bool
    prep_time_minutes: Optional[int] = None
    image_url: Optional[str] = None
    tags: Any = None
    customizations: list[str] = []


class MenuCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    items: list[MenuItemOut] = []


class MenuOut(BaseModel):
    outlet_id: uuid.UUID
    # Carried here too so the menu screen can offer the call button without a
    # second request — it is reached by tapping an outlet, and re-fetching the
    # whole discovery list just for one phone number would be wasteful.
    outlet_phone_number: Optional[str] = None
    categories: list[MenuCategoryOut] = []


# ----------------------------- Orders ---------------------------------------
class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(..., ge=1)
    customizations: Optional[Any] = None
    item_notes: Optional[str] = None


class CreateOrderIn(BaseModel):
    outlet_id: uuid.UUID
    items: list[OrderItemIn] = Field(..., min_length=1)
    customer_notes: Optional[str] = None
    # Optional POINTS_DISCOUNT coupon applied at checkout (migration 010).
    coupon_code: Optional[str] = Field(None, min_length=4, max_length=24)
    # Promotion applied at checkout (migration 016). Two ways in, because the
    # two products reach the customer differently: `promotion_id` is a tap on an
    # offer the app already listed, `promotion_code` is a code typed in from a
    # creator post or a poster.
    #
    # DELIBERATELY SEPARATE from coupon_code. V1 does not stack: sending both a
    # coupon and a promotion is rejected rather than silently applying one, so
    # the customer never sees a total they cannot account for.
    promotion_id: Optional[uuid.UUID] = None
    promotion_code: Optional[str] = Field(None, min_length=3, max_length=24)
    # PE Step 3 (FR-C1/C2): travel context captured at checkout.
    # bike | car | walk | auto | bus | train  (addendum Item 1)
    transport_mode: Optional[str] = None
    # Train orders only: the arrival time the customer typed in. Ignored for
    # every other mode — Leg A for train is a stated time, not a GPS origin.
    declared_arrival_at: Optional[datetime] = None
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    origin_source: Optional[str] = None        # gps | places_autocomplete | none


# --- PE Step 3: customer event inputs ---------------------------------------
class DepartIn(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class LocationPingIn(BaseModel):
    lat: float
    lng: float
    accuracy_m: Optional[float] = None
    speed_mps: Optional[float] = None


class ArrivedIn(BaseModel):
    accuracy_m: Optional[float] = None
    source: str = "geofence"                    # geofence | tap


class WaitFeedbackIn(BaseModel):
    bucket: str = Field(..., pattern=r"^(0|1-3|3-5|5\+)$")


class EventAck(BaseModel):
    ok: bool = True
    recorded: bool = True
    detail: Optional[str] = None


class PaymentBlock(BaseModel):
    gateway: str
    gateway_order_id: str
    amount: int
    currency: str = "INR"
    key_id: Optional[str] = None
    # Cashfree opens its hosted checkout on this token. Null for the
    # Razorpay-shaped stub, which opens on gateway_order_id + key_id — so the
    # app picks its flow from `gateway`, not from a build-time constant.
    payment_session_id: Optional[str] = None


class CreateOrderOut(BaseModel):
    id: uuid.UUID
    status: str
    total_amount: float
    payment: PaymentBlock
    # Price breakdown (migration 016). total_amount stays the amount charged and
    # keeps its meaning for every existing caller; these three are additive so
    # the app can show "₹420 ₹380" without recomputing anything client-side.
    # final_amount == total_amount always — both are returned because the app
    # reads a breakdown, not a total, and a name it has to remember is a bug
    # waiting to happen.
    original_amount: float = 0
    discount_amount: float = 0
    final_amount: float = 0
    # What to name the saving in the UI, e.g. "20% off up to ₹60". Null when no
    # promotion was applied (a points coupon is not a promotion).
    promotion_label: Optional[str] = None


class OrderItemOut(BaseModel):
    id: uuid.UUID
    menu_item_id: Optional[uuid.UUID] = None
    name_snap: Optional[str] = None
    price_snap: float
    quantity: int
    customizations: Any = None
    item_notes: Optional[str] = None


class WaitEstimateOut(BaseModel):
    # §16 shadow-mode range only — never a departure window / σ / confidence.
    low_min: int
    high_min: int
    approximate: bool = True


class OrderOut(BaseModel):
    id: uuid.UUID
    status: str
    payment_status: str
    pickup_code: Optional[str] = None
    total_amount: float
    # Same breakdown as CreateOrderOut, so the order-status and history screens
    # can show what was saved without re-deriving it from the line items.
    original_amount: float = 0
    discount_amount: float = 0
    final_amount: float = 0
    items: list[OrderItemOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    wait_estimate: Optional[WaitEstimateOut] = None


# ---------------------------- Payment ---------------------------------------
class SimulatePaymentIn(BaseModel):
    order_id: uuid.UUID
    method: str = "upi"


class SimulatePaymentOut(BaseModel):
    status: str
    pickup_code: Optional[str] = None


class AdvanceStatusIn(BaseModel):
    status: Optional[str] = None  # optional explicit target; else next in progression


# ------------------------------ POS -----------------------------------------
class VerifyPickupIn(BaseModel):
    order_id: uuid.UUID
    pickup_code: str


class RegisterIn(BaseModel):
    restaurant_name: str = Field(..., min_length=2, max_length=100)

    # City is now chosen from the canonical `cities` list (migration 013), not
    # typed freehand — that is what stopped "Bangalore"/"Bengaluru" diverging.
    # Supply EXACTLY ONE of:
    #   city           -> must already be an active city
    #   requested_city -> a new name, recorded as pending for admin approval
    city: Optional[str] = Field(None, max_length=80)
    requested_city: Optional[str] = Field(None, min_length=2, max_length=80)

    # Locality / area within the city (migration 012). REQUIRED as of this
    # change, following the same pattern phone_number and email already use:
    # the DB column stays nullable so the outlets that predate it keep NULL,
    # and this binds new signups only.
    #
    # Free text, NOT a reference list like `city`. Cities are a short platform
    # list an admin can realistically curate; localities are not — every city
    # has hundreds and they are named inconsistently in real use. The admin
    # approval collision check is what catches the duplicates that matter.
    locality: str = Field(..., min_length=2, max_length=80)

    # Outlet contact number. REQUIRED as of this change: admins had no reliable
    # way to reach an outlet during verification. Existing rows keep NULL — the
    # DB column stays nullable, so this binds new signups only.
    phone_number: str = Field(..., min_length=6, max_length=20)

    # Owner recovery email (migration 015). REQUIRED for new signups — it is
    # what makes forgot-password possible. Stored on `users`, not `outlets`:
    # recovery is per-account, and usernames are unique per user.
    # Existing accounts keep NULL and are prompted to add one after login.
    email: str = Field(
        ..., min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    # Payee VPA (e.g. name@bank) for the upi://pay intent. Required for new
    # signups so the outlet can accept payments; simple "x@y" shape check.
    upi_id: str = Field(..., min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")


    @model_validator(mode="after")
    def _exactly_one_city(self):
        """Reject both-or-neither rather than silently preferring one.

        Accepting both would make it ambiguous whether the owner picked from the
        list or asked for something new, and the two paths differ: one must
        already be approved, the other creates a pending request.
        """
        chosen = (self.city or "").strip()
        requested = (self.requested_city or "").strip()
        if bool(chosen) == bool(requested):
            raise ValueError(
                "Provide either 'city' (from the list) or 'requested_city', not both."
            )
        return self


class RegisterOut(BaseModel):
    outlet_id: uuid.UUID
    username: str
    verification_status: str
    message: str


class VerifyPickupOut(BaseModel):
    verified: bool
    order_id: Optional[uuid.UUID] = None
    status: Optional[str] = None
    locked: Optional[bool] = None
    attempts_remaining: Optional[int] = None


class LookupPickupIn(BaseModel):
    """The code the customer shows at the counter. No order id: staff have the
    code and nothing else, which is the whole point of the lookup.

    The bound is loose rather than the code's own 6 characters because the
    service strips and upper-cases before matching. A tight limit rejects a
    trailing space as a 422 the app cannot explain, instead of the clean
    "not found" (or match) that the same input deserves.
    """
    pickup_code: str = Field(..., min_length=1, max_length=16)


# --------------------- Owner App (staff-authed POS) -------------------------
class OwnerOutletOut(BaseModel):
    id: uuid.UUID
    location_name: str
    is_visible: bool
    image_url: Optional[str] = None


class SetOutletImageIn(BaseModel):
    """Cloudinary URL produced by the app's unsigned upload. Null clears it."""
    image_url: Optional[str] = Field(None, max_length=500)


class SetVisibilityIn(BaseModel):
    is_visible: bool


class SetVisibilityOut(BaseModel):
    id: uuid.UUID
    is_visible: bool


class OwnerMenuItemOut(BaseModel):
    id: uuid.UUID
    name: str
    is_available: bool
    is_active: bool
    base_price: float
    is_veg: bool = True
    prep_time_minutes: Optional[int] = None
    image_url: Optional[str] = None
    category_id: Optional[uuid.UUID] = None
    category_name: Optional[str] = None


class OwnerCategoryOut(BaseModel):
    id: uuid.UUID
    name: str


class CreateMenuItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_price: float = Field(..., ge=0)
    category_id: uuid.UUID
    is_veg: bool = True
    prep_time_minutes: Optional[int] = Field(None, ge=0, le=1440)
    image_url: Optional[str] = Field(None, max_length=1024)


class UpdateMenuItemIn(BaseModel):
    # All optional — a PATCH updates only the fields provided.
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    base_price: Optional[float] = Field(None, ge=0)
    category_id: Optional[uuid.UUID] = None
    is_veg: Optional[bool] = None
    prep_time_minutes: Optional[int] = Field(None, ge=0, le=1440)
    image_url: Optional[str] = Field(None, max_length=1024)
    is_available: Optional[bool] = None


class DeleteMenuItemOut(BaseModel):
    ok: bool
    id: uuid.UUID
    is_active: bool


class SetAvailabilityIn(BaseModel):
    is_available: bool


class SetAvailabilityOut(BaseModel):
    id: uuid.UUID
    is_available: bool


class OwnerOrderLineOut(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    quantity: int


class OwnerOrderOut(BaseModel):
    order_id: uuid.UUID
    status: str
    payment_status: Optional[str] = None
    is_locked: bool
    total_amount: float
    created_at: Optional[datetime] = None
    #: Set once staff confirm the pickup code. The owner app uses it to mark
    #: the row as collected during its 30-minute grace window; the row itself
    #: stops being returned once that window closes (CarevoService.
    #: COMPLETED_GRACE), so the app never has to time the removal itself.
    pickup_verified_at: Optional[datetime] = None
    items: list[OwnerOrderLineOut] = []


class LookupPickupOut(BaseModel):
    """Result of a pickup-code lookup.

    A miss is `found: false` with HTTP 200, not a 404 — the app has to tell
    "no live order has that code" apart from "the request failed", and a
    status code that also means network/route trouble cannot carry that.
    """
    found: bool
    #: True when the order exists but is locked out after 3 failed attempts.
    #: The app shows the lockout rather than a confirm button the server
    #: would only refuse with a 423.
    locked: bool = False
    order: Optional[OwnerOrderOut] = None


class MarkPaidOut(BaseModel):
    order_id: uuid.UUID
    status: str
    payment_status: Optional[str] = None
    pickup_code: Optional[str] = None


class NotifyIn(BaseModel):
    type: str
    item_id: Optional[uuid.UUID] = None


class NotifyOut(BaseModel):
    ok: bool
    delivered: bool
    type: str
    item_id: Optional[uuid.UUID] = None
    item_name: Optional[str] = None


# ------------------- Staff reject / batch N/A (migration 017) ----------------
class RejectOrderIn(BaseModel):
    """Optional free-text captured into the ORDER_REJECTED event. Not shown to
    the customer verbatim in V1 — the push copy is fixed and honest."""
    reason: Optional[str] = Field(default=None, max_length=300)


class RejectOrderOut(BaseModel):
    order_id: uuid.UUID
    status: str
    # True when the order was already CANCELLED — a double-tap, not an error.
    already: bool = False
    reason: Optional[str] = None


class MarkItemsUnavailableIn(BaseModel):
    """One or more line-item ids from THIS order. Duplicates are collapsed
    server-side, so a checklist that somehow submits the same row twice cannot
    produce two events for one item."""
    item_ids: list[uuid.UUID] = Field(..., min_length=1)


class UnavailableMarkedOut(BaseModel):
    item_id: uuid.UUID
    name: Optional[str] = None
    notified: bool = False


class MarkItemsUnavailableOut(BaseModel):
    ok: bool
    order_id: uuid.UUID
    # One entry per item, each with its own event + push already fired.
    marked: list[UnavailableMarkedOut] = []
    delivered: bool = False


class RegisterStaffTokenIn(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=255)


class RegisterStaffTokenOut(BaseModel):
    ok: bool
    registered: bool


class DeleteAccountOut(BaseModel):
    ok: bool
    deleted: bool
    # Order rows survive as business/tax records, detached from any person.
    # Reported back so the confirmation screen can be specific rather than
    # vaguely reassuring.
    orders_retained: int = 0
    message: str


# --------------------- Profile / loyalty / coupons (010) ---------------------
class MeOut(BaseModel):
    """The signed-in customer's own profile.

    `plan` is DERIVED from premium_until, never stored — so there is no second
    field that can drift out of agreement with it. It is a display label only:
    no paid tier exists yet and premium currently unlocks nothing.
    """
    id: uuid.UUID
    name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    points_balance: float = 0
    premium_until: Optional[datetime] = None
    plan: str = "Free"


class UpdateMeIn(BaseModel):
    """Name is the only self-editable field.

    Phone and email are identities established by a verified sign-in flow
    (OTP / Google) and must never be settable by the client asserting them.
    """
    name: str = Field(..., min_length=1, max_length=100)


class OrderHistoryItemOut(BaseModel):
    name: Optional[str] = None
    quantity: int = 1


class OrderHistoryOut(BaseModel):
    order_id: uuid.UUID
    outlet_id: uuid.UUID
    outlet_name: Optional[str] = None
    status: str
    payment_status: Optional[str] = None
    total_amount: float = 0
    discount_amount: float = 0
    created_at: Optional[datetime] = None
    # Null until payment lands. Present here so an in-progress order can be
    # reopened from history — previously the code was only ever shown on the
    # transient post-checkout screen and was unrecoverable once left.
    pickup_code: Optional[str] = None
    items: list[OrderHistoryItemOut] = []


class PointTransactionOut(BaseModel):
    id: uuid.UUID
    order_id: Optional[uuid.UUID] = None
    points_delta: float
    reason: str
    created_at: Optional[datetime] = None


class PointsOut(BaseModel):
    points_balance: float = 0
    # Mirrors the service constants so the client never hardcodes the rule.
    redemption_threshold: float = 50
    redemption_value_rupees: float = 100
    can_redeem: bool = False
    transactions: list[PointTransactionOut] = []


class CouponOut(BaseModel):
    id: uuid.UUID
    code: str
    kind: str
    discount_amount: float = 0
    trial_days: int = 0
    status: str
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class RedeemPointsOut(BaseModel):
    coupon: CouponOut
    points_balance: float
    message: str


class RedeemCouponIn(BaseModel):
    code: str = Field(..., min_length=4, max_length=24)


class RedeemCouponOut(BaseModel):
    kind: str
    premium_until: Optional[datetime] = None
    plan: str = "Free"
    message: str


# ------------------- Cart availability pre-check (Task 5) --------------------
class CartCheckIn(BaseModel):
    outlet_id: uuid.UUID
    menu_item_ids: list[uuid.UUID] = Field(default_factory=list)


class UnavailableItemOut(BaseModel):
    menu_item_id: uuid.UUID
    # Null when the item was deleted from the menu outright, not just disabled.
    name: Optional[str] = None


class CartCheckOut(BaseModel):
    ok: bool
    unavailable: list[UnavailableItemOut] = []


# ---------------------- Location areas (derived, not fixed) ------------------
class AreaOut(BaseModel):
    """One selectable city, derived from outlets that are actually orderable.

    `outlet_count` lets the app show "3 restaurants" instead of a bare name, and
    is always >= 1 by construction — a city with no outlets is never returned.
    """
    city: str
    outlet_count: int


# ---------------------- Canonical cities (migration 013) ---------------------
class CityOut(BaseModel):
    """One selectable city for the owner signup dropdown."""
    id: uuid.UUID
    name: str
