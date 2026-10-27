"""Pydantic v2 schemas for CareVo Skip customer + payment flows."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

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
class TransportModeOut(BaseModel):
    """One travel mode a city offers (migration 030).

    `uses_declared_arrival` is the load-bearing field: it tells the app to swap
    the origin resolution for a time picker WITHOUT the app needing to know the
    mode by name. That is what makes a mode added server-side work in a build
    that predates it — it renders with a fallback icon and behaves correctly.
    """
    code: str
    label: str
    uses_declared_arrival: bool = False


class OutletOut(BaseModel):
    id: uuid.UUID
    name: str
    address: Optional[str] = None
    # Operating hours (migration 024). is_open is now REAL (was hardcoded True):
    # true only when new orders are accepted. order_status is the three-state
    # label the app renders — "open" | "closing_soon" | "closed" — and
    # closed_reason is the staff-/customer-facing sentence for the latter two.
    # opening_time/closing_time (HH:MM, local) back the "9:00 AM – 10:00 PM" line
    # and match the field names customer_app's Outlet model already parses.
    is_open: bool = True
    order_status: str = "open"
    closed_reason: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    distance_km: Optional[float] = None
    # When this outlet joined. Backs the app's "Newest" sort; Optional because
    # the column is nullable on rows that predate the current schema.
    created_at: Optional[datetime] = None
    upi_id: Optional[str] = None
    # Area within the city (migration 012). Null for outlets that predate it —
    # the app then renders the name alone rather than a dangling separator.
    locality: Optional[str] = None
    # The city as its own field, not just the tail of `address`.
    #
    # `address` is built here as ", ".join(locality, city), so until now the
    # only way for a client to know the city was to split that string on the
    # last comma — which breaks for outlets predating migration 012, where
    # `address` IS the bare city and there is nothing to split.
    #
    # Surfaced because the checkout screen needs the city to decide which
    # transport modes to offer, and a display string is the wrong thing to key
    # behaviour off. The column was already SELECTed in list_outlets; this only
    # stops it being dropped before serialising. Purely additive.
    city: Optional[str] = None
    # --- City transport profile (migration 029) ------------------------------
    # The server's answer to "which travel modes does this city support", so an
    # admin toggling a city to "metro" lights the option up in an already
    # installed app. Before this the answer was a const map compiled into
    # customer_app, and a new metro city needed a store release.
    #
    # All three are Optional and default to None, and None is NOT False:
    #   None  -> this deployment has no answer (pre-029 backend, or a city with
    #            no `cities` row). The app falls back to its built-in map.
    #   False -> an admin has said this city does not have it.
    # Collapsing the two would make an un-migrated backend strip Train from
    # every city that offers it today.
    city_type: Optional[str] = None          # metro | tier_1 | tier_2 | tier_3
    has_metro: Optional[bool] = None
    has_train: Optional[bool] = None
    # --- The real answer as of migration 030 ---------------------------------
    # Every mode enabled for this outlet's city, in display order, each
    # carrying whether it is satisfied by a declared arrival TIME rather than a
    # GPS origin. Behaviour travels with the data, so an app build that has
    # never heard of a mode still handles it correctly — which is what lets a
    # ninth mode be added without an app release.
    #
    # has_metro/has_train above are DERIVED from this same list and kept only
    # for builds already installed, which read those keys and know nothing
    # about this one.
    transport_modes: Optional[list[TransportModeOut]] = None
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
    # --- Payment methods (migration 034) -------------------------------------
    # What this outlet can take, in display order: ["PREPAID"],
    # ["PAY_AT_PICKUP"], or both. Server-driven for the same reason
    # transport_modes is (030): switching an outlet to pay-at-pickup is one
    # admin toggle, and it has to light up in an already-installed app.
    #
    # An EMPTY LIST is a real answer, not a missing one — a prepaid-only outlet
    # on a deployment with no live gateway can take no orders. The app should
    # treat it as "not orderable right now" rather than defaulting to prepaid.
    #
    # Resolved WITHOUT a customer on this endpoint, so it is an upper bound:
    # pay-at-pickup additionally requires a verified phone, no open unpaid
    # pickup order and fewer than 2 no-shows, all of which POST /orders
    # re-checks against the actual caller.
    payment_methods: list[str] = []


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
    # Same list OutletOut carries, and carried here for the same reason the
    # phone number is: the menu screen is where checkout starts, and it should
    # not need a second request to know whether to offer "Pay at pickup".
    #
    # Resolved WITH the signed-in customer here — unlike the discovery list,
    # this endpoint always has one — so it reflects their verified phone, their
    # open-order state and their no-show strikes. It is therefore the list
    # checkout should actually render.
    payment_methods: list[str] = []
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
    # How this order will be paid (migration 034). 'PREPAID' | 'PAY_AT_PICKUP'.
    #
    # ABSENT MEANS PREPAID, and that is the entire backwards-compatibility
    # story. An already-installed customer_app build has no such field to send,
    # so it implicitly asks for prepaid — which is exactly what it has always
    # asked for. At a pay-at-pickup-only outlet that request is refused with a
    # 409 carrying prose the app renders verbatim, and no order row is created.
    #
    # NOT validated against a pattern here on purpose. The authority on which
    # methods exist for THIS outlet and THIS customer is
    # CarevoService.payment_methods_for, and a 422 from Pydantic would answer a
    # different question ("is this a known string") with a message the app
    # cannot show anybody. An unknown value falls through to the same 409 as a
    # known-but-unavailable one. 'UPI_MANUAL' is reserved in the database CHECK
    # but is never offered, so asking for it is refused like any other.
    payment_method: Optional[str] = Field(None, max_length=20)
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
    # Scheduled pickup (migration 031). The time the customer chose to collect.
    # Absent/NULL = order now, which is every order placed before this shipped.
    #
    # NOT mutually exclusive with declared_arrival_at at the API boundary, on
    # purpose. A train passenger who also schedules a pickup has given two real
    # pieces of information and refusing the pair would discard one of them —
    # declared_arrival_at still feeds predict_travel's `customer_declared` leg.
    # What IS exclusive is which of the two may WAKE THE KITCHEN: release_at
    # wins, and _notify_kitchen_for_due_trains is suppressed for held orders.
    requested_pickup_at: Optional[datetime] = None


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


class UpiPaymentBlock(BaseModel):
    """Everything the app needs to build a `upi://pay?...` intent (035).

    Computed server-side because the VPA and payee are the RESTAURANT's and the
    app has no other way to learn them, and because `note` has to match what
    the restaurant will see in its own UPI app beside the amount.

    `note` is the short order number — deliberately NOT the pickup code, which
    must never travel through a payment app or appear on a bank statement.
    """
    vpa: str
    payee_name: str = ""
    amount: float
    #: The short order number, for the UPI `tn=` field.
    note: str


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
    # OPTIONAL since migration 034. A pay-at-pickup order has no gateway
    # session, so there is nothing to put here and the field is absent rather
    # than filled with a synthetic block — a fake gateway id is a thing some
    # client would eventually try to open a checkout with.
    #
    # Additive for the deployed app's PARSER: CreatedOrder.fromJson already
    # tolerates a missing `payment` and yields null (order.dart:77-79). It is
    # NOT behaviourally safe for that build, which would then route to the
    # simulate screen — which is why a pay-at-pickup order is refused at
    # create_order for a client that did not ask for one, and this field is
    # never null for a request that omitted payment_method.
    payment: Optional[PaymentBlock] = None
    # 'PREPAID' | 'PAY_AT_PICKUP'. Echoed on both paths so the app reads one
    # field rather than inferring the mode from `payment` being null.
    payment_mode: str = "PREPAID"
    #: What the customer will hand over at the counter. 0 for a prepaid order.
    amount_due_at_pickup: float = 0
    #: Present only for a UPI_MANUAL order, and only while payment is pending.
    #: Absent (not an empty object) for every other mode, so a client can test
    #: for it rather than inspecting its fields.
    upi_payment: Optional[UpiPaymentBlock] = None
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
    # Customer's own pickup-journey acknowledgments, sourced from order_events
    # (migration 023). Additive: every existing client ignores unknown fields,
    # and these default False for any order with no such events yet. Exposed so
    # the app can eventually restore travel/pickup state from the server instead
    # of trusting only on-device persistence. None of these move order.status —
    # staff PICKUP_VERIFIED is still the only real completion.
    departed: bool = False
    arrived: bool = False
    picked_up: bool = False
    # Scheduled pickup (migration 031). Both NULL for an ASAP order, which is
    # every order an already-installed build can produce — and an unknown field
    # is ignored by those builds, so this is additive in both directions.
    #
    # requested_pickup_at is what the app RENDERS ("Scheduled for 7:30 pm"):
    # it is the customer's own choice and never moves. release_at is the
    # internal decision and is deliberately also exposed, because without it a
    # held order and a released one are indistinguishable on the client — the
    # status is PAID either way — and the app would have to guess which of its
    # two states to draw.
    requested_pickup_at: Optional[datetime] = None
    release_at: Optional[datetime] = None

    # Manual acceptance + refunds (migration 032). ADDITIVE in both directions:
    # None/False for every order at an acceptance_mode='auto' outlet — which is
    # every outlet until one opts in — and an already-installed build ignores
    # unknown fields.
    #
    # acceptance_state is what the app GATES ON. Its presence is the signal
    # that this outlet requires confirmation, which is why the client must test
    # for null rather than for a status: an awaiting order's status is PAID,
    # exactly like an auto order's, so status alone cannot tell them apart.
    #
    # acceptance_deadline_at is exposed so the app can show a countdown rather
    # than an indefinite spinner — "waiting" with no visible end is the worst
    # version of this screen.
    acceptance_state: Optional[str] = None
    acceptance_deadline_at: Optional[datetime] = None
    #: True when money was taken and no food will be delivered. Drives the
    #: customer-facing refund message.
    refund_required: bool = False

    # Pay at pickup (migration 034). ADDITIVE in both directions: 'PREPAID'
    # and 0 for every order an already-installed build can produce, and that
    # build ignores fields it does not know.
    #
    # DELIBERATELY NO CONTACT FIELDS HERE. The customer's own phone and name
    # are snapshotted on the order, but echoing them back to the customer who
    # supplied them adds nothing and widens the surface on which they can leak.
    # The outlet reads them through the staff-authed owner queue; nobody reads
    # them here.
    payment_mode: str = "PREPAID"
    #: What to hand over at the counter. 0 for a prepaid order.
    amount_due_at_pickup: float = 0
    #: NULL for a prepaid order. PENDING | CALLED | UNREACHABLE — lets the app
    #: say "they're about to call you" rather than showing a bare spinner.
    call_state: Optional[str] = None
    # --- Direct UPI (migration 035) ------------------------------------------
    #: Set once the customer has tapped "I've paid". Its presence is what moves
    #: the pay screen from "pay now" to "waiting for the restaurant", so the
    #: state survives the app being killed and reopened.
    payment_claimed_at: Optional[datetime] = None
    #: The restaurant owes this money back directly. Drives the customer-facing
    #: "they will refund you" message, which is honest about WHO refunds:
    #: CareVo cannot, because it was never in the payment path.
    manual_refund_due: bool = False
    manual_refund_reason: Optional[str] = None
    #: Present only while a UPI order is unpaid, so the pay screen can be
    #: rebuilt after a restart. Absent once accepted.
    upi_payment: Optional[UpiPaymentBlock] = None


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
    # Operating hours + manual closure (migration 024). Times are HH:MM local;
    # order_status lets the owner see the same live state a customer would.
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    is_manually_closed: bool = False
    order_status: str = "open"
    # Pin the customer app sorts by distance on. Null until the owner sets it.
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SetOutletLocationIn(BaseModel):
    """Coordinates from the owner's own device, via "Use current location".

    Both required: half a coordinate pair is not a location, and allowing one
    without the other would let a partial write leave a pin at (lat, 0) — a
    point in the Gulf of Guinea that the distance sort would happily use.
    """
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class SetHoursIn(BaseModel):
    """Daily opening/closing schedule, HH:MM (24h) local, or null to clear."""
    opening_time: Optional[str] = Field(None, pattern=_HHMM)
    closing_time: Optional[str] = Field(None, pattern=_HHMM)


class SetManualClosedIn(BaseModel):
    is_manually_closed: bool


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
    #: Limited quantity (migration 033). None = UNTRACKED (unlimited), which is
    #: every item until an owner sets a number — and the reason this is
    #: Optional rather than defaulting to 0, since 0 means "sold out".
    stock_remaining: Optional[int] = None
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
    #: Manual acceptance (migration 032). ADDITIVE and Optional: None for every
    #: order at an `acceptance_mode='auto'` outlet, which is every outlet until
    #: one opts in — so an owner_app build that does not know these fields
    #: exist is unaffected.
    acceptance_state: Optional[str] = None
    acceptance_deadline_at: Optional[datetime] = None
    # --- Pay at pickup (migration 034) ---------------------------------------
    # ALL SEVEN ARE ADDITIVE AND OPTIONAL, and every one of them is None/0/False
    # for a PREPAID order — which is every order at every outlet until an admin
    # switches one on. A deployed owner_app build reads a fixed key list
    # (order.dart:110-129) and is therefore completely unaffected.
    #
    # THIS NARROWS A DOCUMENTED INVARIANT, and it is worth being explicit about
    # rather than letting someone discover it: the owner queue is described as
    # NAME-FREE in three places (orders_screen.dart, owner_app's Order model,
    # and list_active_orders' own docstring). Pay-at-pickup cannot work without
    # a name and a number — somebody has to ring the customer — so the
    # invariant now holds for PREPAID orders only. It is not quietly gone; it
    # is scoped, and the fields below are null wherever it still applies.
    payment_mode: Optional[str] = None
    #: FIRST NAME ONLY. A surname is extra personal data with no operational
    #: use at a counter — "Asha" is what gets called out.
    contact_first_name: Optional[str] = None
    #: Suppressed once the visibility window closes, even though the row still
    #: holds it, and nulled for good by the 30-day redaction sweep.
    contact_phone: Optional[str] = None
    #: Whether the contact above is being returned at all, so the app can draw
    #: "contact no longer available" instead of an empty space that looks like
    #: a bug.
    contact_visible: bool = False
    #: PENDING | CALLED | UNREACHABLE. Null for a prepaid order.
    call_state: Optional[str] = None
    call_attempts: int = 0
    #: cash | upi, once the money has been taken.
    collected_payment_method: Optional[str] = None
    # --- Direct UPI (migration 035) ------------------------------------------
    # All three additive and NULL/false for every other mode.
    #
    # payment_claimed_at is what the owner app gates its "Customer says paid"
    # state on — NOT a payment. The restaurant confirms the money by looking at
    # its own UPI app, and that confirmation is the Accept tap.
    payment_claimed_at: Optional[datetime] = None
    #: The RESTAURANT owes this customer money directly. Never the gateway
    #: refund queue — CareVo was not in the payment path and cannot reverse it.
    manual_refund_due: bool = False
    manual_refund_reason: Optional[str] = None
    items: list[OwnerOrderLineOut] = []


class AcceptOrderIn(BaseModel):
    """`prep_minutes` is the restaurant's OWN estimate, and is required.

    Required rather than defaulted because the whole point of a manual accept
    is that a human looked at the order and formed a view; a silent default
    would record a promise nobody made. It is stored in
    prep_minutes_committed for later comparison against order_outcome — the
    customer-facing ETA still comes from the prediction engine, not from this.
    """

    prep_minutes: int = Field(..., gt=0, le=240)


class AcceptOrderOut(BaseModel):
    order_id: uuid.UUID
    status: str
    acceptance_state: str
    prep_minutes: int


# ------------- Owner self-serve payment settings (migration 035) ------------
class OwnerPaymentMethodsOut(BaseModel):
    """What this outlet accepts, and what it is permitted to accept."""
    outlet_id: uuid.UUID
    prepaid: bool
    pay_at_pickup: bool
    upi_manual: bool
    #: PLATFORM permission for online payment, not an owner preference. False
    #: means the owner app renders the Cashfree toggle locked with a reason
    #: rather than a switch that flips back.
    cashfree_unlocked: bool
    upi_vpa: Optional[str] = None
    upi_payee_name: Optional[str] = None
    #: Derived from upi_attested_at, so the client has a boolean for its
    #: checkbox rather than having to interpret a timestamp.
    upi_attested: bool = False
    updated_at: Optional[datetime] = None
    #: What a customer would actually be offered right now — which is NOT just
    #: the three flags, since prepaid also needs the unlock and a gateway.
    effective_methods: list[str] = []


class OwnerPaymentMethodsIn(BaseModel):
    """The FULL desired state, not a delta.

    All three flags are required for the same reason the admin route requires
    both of its own: a partial update is how an outlet ends up accepting
    nothing, and stating the end state makes the request unambiguous.
    """
    prepaid: bool
    pay_at_pickup: bool
    upi_manual: bool
    #: Max length matches ck_outlets_upi_vpa_shape's own bound. The shape is
    #: validated in the service so a bad value is a sentence, not a 422 the
    #: owner app cannot render.
    upi_vpa: Optional[str] = Field(None, max_length=320)
    upi_payee_name: Optional[str] = Field(None, max_length=120)
    #: "I sent myself Rs 1 using this UPI ID and received it."
    #:
    #: The only check that proves a VPA reaches the person who typed it. Sent
    #: as a transient confirmation rather than stored state — the server
    #: stamps upi_attested_at from it, and CHANGING THE VPA VOIDS IT, so an
    #: owner editing their UPI ID must tick it again.
    upi_attested: bool = False


# ---------------------- Pay at pickup (migration 034) ------------------------
class CallPlacedOut(BaseModel):
    order_id: uuid.UUID
    call_state: str
    #: Counts up — a second attempt is a real thing, not an error.
    call_attempts: int


class CollectOrderIn(BaseModel):
    """The code the customer shows, and how they paid.

    `pickup_code` is REQUIRED, so taking money cannot be decoupled from
    checking that this is the right order — the same gate the prepaid handover
    has always had, with payment attached.
    """
    pickup_code: str = Field(..., min_length=1, max_length=16)
    #: cash | upi. Not a free-text field: these two are what a counter can
    #: actually take, and the DB CHECK enforces the same pair.
    method: str = Field(..., pattern=r"^(cash|upi)$")


class CollectOrderOut(BaseModel):
    #: False for a wrong code — a 200 with collected=false, not a 4xx, for the
    #: same reason LookupPickupOut reports a miss that way: the app must tell
    #: "wrong code" apart from "the request failed".
    collected: bool
    order_id: uuid.UUID
    status: Optional[str] = None
    payment_status: Optional[str] = None
    collected_payment_method: Optional[str] = None
    attempts_remaining: Optional[int] = None
    locked: Optional[bool] = None


class ClaimPaidOut(BaseModel):
    """Result of the customer tapping "I've paid" (035).

    `claimed` is the state, `already` distinguishes the second tap of a
    double-tap from the first — the same shape AlertAckOut uses, and for the
    same reason: a repeat is normal, not an error.
    """
    order_id: uuid.UUID
    claimed: bool
    already: bool = False
    payment_claimed_at: Optional[datetime] = None
    status: Optional[str] = None


class NoShowOut(BaseModel):
    order_id: uuid.UUID
    status: str
    no_show: bool = True


class AlertAckOut(BaseModel):
    order_id: uuid.UUID
    #: False when the order was no longer AWAITING — an ack racing the
    #: resolution it describes is normal, not an error.
    acknowledged: bool


class SetStockIn(BaseModel):
    """`quantity=None` means UNTRACKED (unlimited), not zero.

    The distinction is the whole design: NULL is "we do not count this dish",
    which is every item today and therefore the inert default; 0 is "we counted
    and there are none left". Collapsing them would make turning tracking off
    indistinguishable from selling out.
    """

    quantity: Optional[int] = Field(default=None, ge=0, le=100000)


class SetStockOut(BaseModel):
    id: uuid.UUID
    name: str
    #: None = untracked.
    stock_remaining: Optional[int] = None
    #: Echoed because setting stock can flip it — 0 hides the dish, and a
    #: positive number on a sold-out dish brings it back.
    is_available: bool


class TestPushOut(BaseModel):
    """Result of POST /pos/devices/test-push.

    Returns the TRANSPORT outcome rather than a bare ok, because 'skipped'
    with a reason is the useful case: "no fcm_token" (this device never
    registered — grant notification permission), "push disabled" (an operator
    problem, stop investigating) and a 4xx from FCM have three different fixes,
    and a plain success/failure cannot tell them apart.
    """

    #: sent | skipped | failed
    status: str
    detail: Optional[str] = None


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
    #: "We rang and could not reach them" (migration 034). A SEPARATE flag
    #: rather than a magic `reason` string, because the server has to branch on
    #: it (it writes call_state and its own event) and matching on free text
    #: the staff typed would be the wrong way to decide that.
    #:
    #: Ignored for a prepaid order, which has no call to have failed.
    unreachable: bool = False
    #: Direct UPI only (035): WHICH kind of no this is.
    #:
    #:   not_received — the money is not in the restaurant's UPI app. The
    #:       customer claimed a payment that did not happen: their strike,
    #:       nothing owed.
    #:   cannot_make  — the money IS there and the kitchen cannot cook it. The
    #:       restaurant owes it back directly, UPI to UPI.
    #:
    #: A closed set rather than free text, because the server branches on it
    #: and matching prose a staff member typed would be the wrong way to decide
    #: who is owed money. Ignored unless the order is a claimed UPI order.
    upi_outcome: Optional[Literal["not_received", "cannot_make"]] = None


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
