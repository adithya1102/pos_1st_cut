"""Business logic for CareVo Skip (customer pre-order / pickup)."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import secrets
import string
import time
import uuid
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.websocket_manager import customer_manager, pos_manager
from app.modules.customers.model import Customer
from app.modules.carevo_customer.model import (
    Coupon,
    CustomerOrder,
    CustomerOrderItem,
    PaymentTransaction,
    PointTransaction,
)
from app.modules.carevo_payments.gateway import (
    GatewayConfigError,
    GatewayRequestError,
    get_gateway,
)
from app.modules.prediction import events as pe
# Safe at module level: promotions.service imports only its own schema, so this
# closes no cycle (promotions.controller reaches back into carevo_customer.deps,
# never into this module).
from app.modules.promotions.service import PromotionService

# --- OTP rate limiter -------------------------------------------------------
# NOTE: single-process limiter; use Redis in prod
_otp_hits: dict[str, list[float]] = defaultdict(list)
# Per-IP limiter for public owner self-signup (POST /register), same pattern.
_register_hits: dict[str, list[float]] = defaultdict(list)
# Per-OUTLET limiter for pickup-code misses, same pattern and same caveat.
# Keyed by outlet rather than by IP or order: the thing being guarded is the
# guessing of codes at one counter, and every request already arrives with an
# authenticated staff account whose outlet_id is the natural bucket.
_pickup_miss_hits: dict[str, list[float]] = defaultdict(list)
# STAFF LOGIN limiter, shared by /auth/login and /auth/pin-login. Same pattern,
# same single-process caveat.
#
# Keyed on BOTH the claimed identifier and the client IP, each counted in its
# own bucket, because the two attacks are different shapes: one attacker
# grinding many PINs at one account is caught by the username bucket, and one
# attacker spraying one PIN across many accounts is caught by the IP bucket.
# Either bucket filling is enough to refuse.
#
# A 4-digit PIN is 10,000 values; without this, nothing at all stood between an
# attacker and exhausting that space against a known username.
_login_hits: dict[str, list[float]] = defaultdict(list)
# Per-STAFF-USER limiter for the self-service test push. Same pattern, same
# single-process caveat. Keyed on the authenticated user id rather than an IP,
# because the endpoint only ever pushes to the CALLER's own device — there is
# no way to aim it at anyone else, so the thing being rationed is one person
# spamming their own tablet (and our FCM quota), not an attack.
_test_push_hits: dict[str, list[float]] = defaultdict(list)

# Default categories seeded for every self-registered outlet, so the owner has
# real options in the dish form's category picker immediately. Order = display.
DEFAULT_CATEGORIES = ["Starters", "Mains", "Sides", "Desserts", "Beverages"]

logger = logging.getLogger(__name__)

# Status progression for the pickup flow
_PROGRESSION = ["RECEIVED", "PREPARING", "READY"]
_LIVE_STATUSES = {"PAID", "RECEIVED", "PREPARING", "READY"}

# Finished, from the CUSTOMER's point of view — the order is over and they have
# been told so. A payment landing against one of these cannot reopen it: see the
# guard in mark_paid. PICKED_UP is included alongside the three the app can
# currently produce because it is terminal in exactly the same sense (the client
# treats it as collected) and a future writer of it must not reopen a gap this
# guard was added to close.
_TERMINAL_STATUSES = {"CANCELLED", "COMPLETED", "ABANDONED", "PICKED_UP"}

# Operating-hours gate (migration 024). Kept as named constants so they are easy
# to tune later without hunting through query strings.
#
# New orders are refused within ORDER_CUTOFF_MINUTES of closing, so the kitchen
# is never handed an order it cannot finish before the doors shut. All outlets
# are in India, and `opens_at`/`closes_at` are stored as bare local time-of-day,
# so the "what time is it now" comparison is done in IST — never the server's
# UTC, which would gate orders against the wrong clock (the same class of bug as
# the greeting that read UTC).
ORDER_CUTOFF_MINUTES = 30
_OUTLET_TZ = ZoneInfo("Asia/Kolkata")

# Availability states, surfaced to the customer and used to gate order creation.
AVAIL_OPEN = "open"
AVAIL_CLOSING_SOON = "closing_soon"
AVAIL_CLOSED = "closed"

# --- universal arrival-feasibility gate (migration 031) ----------------------
# ONE message for every way an order can be infeasible: the requested slot is in
# the past, beyond the scheduling horizon, or the customer's ESTIMATED arrival
# lands when the outlet is closed or inside its pre-close cutoff.
#
# Deliberately one string rather than a reason per case. The customer's remedy
# is identical in all of them — pick a different time, or come back later — and
# a gate that explains its internal taxonomy ("your haversine ETA exceeds the
# cutoff") tells them nothing they can act on. The precise reason is recorded
# server-side in the prediction log instead, where it is actually useful.
#
# NOTE: distinct from outlet_availability's own `reason` strings, which stay
# exactly as they were. Those answer "why can't I order NOW" about a shop that
# is shut; this one answers "why not for THIS time" about a shop that is open.
ARRIVAL_INFEASIBLE_MESSAGE = (
    "We're sorry — we're not able to take orders for this pickup time. "
    "Please try a different time or check back later."
)

# --- pay at pickup (migration 034) -----------------------------------------
#: The two payment methods a customer can be OFFERED. 'UPI_MANUAL' exists in
#: the database CHECK as a reserved value but is deliberately absent here:
#: nothing writes it, so nothing may offer it either.
PAY_PREPAID = "PREPAID"
PAY_AT_PICKUP = "PAY_AT_PICKUP"
#: Direct UPI (migration 035): the customer pays the restaurant's own VPA from
#: their own UPI app. 034 reserved this value in the DB CHECK precisely so
#: enabling it would be a code change rather than a constraint swap.
PAY_UPI_MANUAL = "UPI_MANUAL"

#: Every method a customer can be offered, in the order they are presented.
_OFFERABLE_METHODS = (PAY_PREPAID, PAY_AT_PICKUP, PAY_UPI_MANUAL)

#: Methods whose money does NOT arrive through the gateway, so no gateway order
#: is created and no payment session exists. Both snapshot the customer's
#: contact, both refuse scheduling, and both share the open-order cap.
_NON_GATEWAY_METHODS = (PAY_AT_PICKUP, PAY_UPI_MANUAL)

#: No-shows before pay-at-pickup stops being offered to a customer. They are
#: not locked out of the product — they are asked to prepay instead.
NO_SHOW_STRIKE_LIMIT = 2

#: False payment claims before direct UPI stops being offered to a customer.
#:
#: A SEPARATE counter from no_show_count, and a separate threshold, because the
#: two are different kinds of bad behaviour: a no-show wasted food that was
#: cooked, a false claim asserted money that was never sent. Collapsing them
#: would make a first offence of either look like a second of one.
FALSE_CLAIM_STRIKE_LIMIT = 2

#: How long a direct-UPI order waits for the customer to say they have paid.
#:
#: MUST STAY BELOW STOCK_HOLD_TTL_SECONDS (600), for the same reason
#: call_window_s does: the stock is HELD until the claim commits it, and a pay
#: window longer than the hold would hand the units back while the customer was
#: still in their UPI app. 480 leaves two minutes of headroom. There is a test
#: that fails if this relationship is ever inverted.
UPI_PAY_WINDOW_SECONDS = 480

#: The PAYMENT_GATEWAY value meaning "nobody chose one" (config.py). Kept as a
#: named constant here so the comparison below reads as a decision rather than
#: as a magic string.
_GATEWAY_UNSET = "unset"


def _gateway_can_charge() -> bool:
    """Can this deployment open a checkout at all?

    NOT the same question as `PaymentGateway.is_live`, and the difference is
    the whole reason this function exists rather than a one-line attribute
    read. `is_live` answers "may a webhook from this gateway be TRUSTED" — it
    is False for the stub precisely because the stub has no counterparty to
    have signed anything, which is what lets /customer/payment/webhook 503
    instead of parsing an unauthenticatable body.

    Offering PREPAID is a different question: "if the customer taps pay, will
    they get a working payment session?" The stub answers yes — it returns a
    Razorpay-shaped order and /payment/simulate completes it, which is how the
    whole flow is walkable locally and how the test suite exercises it. Gating
    the offer on is_live would therefore have withdrawn prepaid from every
    development and test deployment, which is not what "switch Cashfree off"
    means.

    So the selector is PAYMENT_GATEWAY itself, which config.py already
    establishes as the deliberate choice — its default is the non-gateway
    sentinel 'unset' specifically so that forgetting to set it does not quietly
    produce working-looking fake payments. That maps onto exactly what is
    needed here:

      cashfree -> a real gateway was chosen. Prepaid offered.
      stub     -> fake payments were chosen DELIBERATELY (local dev, the
                  suite). Prepaid offered; behaviour unchanged from today.
      unset    -> nobody chose. Prepaid NOT offered.
      anything else -> treated as unset. get_gateway() falls back to the stub
                  for unrecognised values, but a typo is not a decision, and
                  this is the safe direction for one to fail in.

    Switching Cashfree off server-side is therefore PAYMENT_GATEWAY=unset (or
    removing it), which withdraws prepaid everywhere and leaves pay-at-pickup
    as the only method — without deleting a line of Cashfree code.
    """
    return (settings.PAYMENT_GATEWAY or _GATEWAY_UNSET).lower() in {
        "cashfree", "stub",
    }

#: How long a pay-at-pickup order's contact details stay readable to the outlet
#: after the order reaches a terminal status.
#:
#: A disputed handover and a no-show callback both happen inside the hour, and
#: the restaurant may legitimately need to ring back about food it is holding.
#: After this the API stops returning them; the row is cleared for good by the
#: redaction sweep below.
#:
#: Honest limit: suppression stops NEW reads. It cannot un-render a tablet that
#: already fetched the row, so this window — not the sweep — is the real bound
#: on exposure.
CONTACT_VISIBLE_AFTER_TERMINAL = timedelta(hours=2)

#: When the contact snapshot is destroyed outright.
CONTACT_REDACTION_AFTER = timedelta(days=30)

#: Statuses at which a pay-at-pickup order is over, for the contact-visibility
#: window. Spelled separately from _TERMINAL_STATUSES because that set carries
#: PICKED_UP, which nothing writes — including it here would be dead SQL.
_CONTACT_TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "ABANDONED")

# How far ahead a pickup may be scheduled. Same-day by intent, but expressed as
# a duration because "same day" is not well defined for an outlet whose window
# crosses midnight (18:00 -> 02:00): for those, today ends at closes_at, which
# the calendar would call tomorrow. See the arrival gate.
#
# It is also a correctness guard, not just a product limit. outlet_availability
# compares MINUTE-OF-DAY only, so a request 26 hours out would wrap around and
# evaluate as open. Bounding the horizon below 24h makes that impossible.
SCHEDULED_MAX_AHEAD_S = 14 * 3600

# --- scheduled-order feasibility gate (launch blocker) ----------------------
# Used only when an ordered item's prep_time_minutes is NULL (no timing data
# yet) in _estimate_prep_seconds. Deliberately on the slow side: a refusal
# that turns out to have been avoidable costs the customer a re-pick; an
# acceptance that turns out to have been too soon costs the kitchen a
# scheduled order it cannot make, which is the failure this gate exists to
# prevent.
DEFAULT_PREP_MINUTES_IF_UNKNOWN = 15


class CarevoService:
    #: How long a verified pickup stays in the owner app's LIVE order queue
    #: after staff confirm it, before dropping out of the default view.
    #:
    #: Server-side and derived from customer_orders.pickup_verified_at, so the
    #: window survives app restarts and is identical on every device looking at
    #: the same outlet. Only /pos/orders honours it — order history and the
    #: admin order log are unaffected.
    COMPLETED_GRACE = timedelta(minutes=30)

    #: Instant the seven demo outlets were renamed to their current identities
    #: (2026-08-20 21:10:32.960232 IST = 15:40:32.960232 UTC). Taken from the
    #: created_at that the single rename transaction stamped on all 42 inserted
    #: menu_items — the transaction's own clock, not an estimate from the backup
    #: filename or a rounded wall-clock guess.
    #:
    #: Orders older than this belong to the outlet's PREVIOUS identity (Spice
    #: Route Kitchen, Rudrarthi, Bistro, ...) and are hidden from the owner app
    #: so a new restaurant does not open its queue onto a stranger's history.
    #:
    #: COSMETIC ONLY — a WHERE clause, never a delete. All 82 customer_orders
    #: and every customer_order_items row stay exactly as they are, and the
    #: ADMIN order log deliberately still shows the full history: it reads its
    #: own queries in carevo_admin/service.py and does not pass through here.
    #:
    #: One timestamp covers all seven because the rename was one transaction.
    #: If outlets are ever re-identified individually this must become a
    #: per-outlet column rather than a constant.
    #:
    #: Overridable via RENAME_CUTOFF_ISO. The tests set it to the epoch, which
    #: disables the filter: a test database is built from scratch and has no
    #: pre-rename orders, so applying a real-world cutoff there only couples the
    #: suite to one production data event. It also sidesteps a genuine trap —
    #: models default these columns to the NAIVE `datetime.utcnow`, and
    #: SQLAlchemy's asyncpg dialect localises a naive value using the CLIENT
    #: machine's timezone before binding it to timestamptz. On an IST developer
    #: box a "now" order is therefore written 5h30m in the past. Render runs UTC
    #: so production rows are correct, but a local run is not.
    RENAME_CUTOFF = datetime.fromisoformat(
        os.getenv("RENAME_CUTOFF_ISO", "2026-08-20T15:40:32.960232+00:00")
    )

    # ------------------------------ OTP ------------------------------------
    @staticmethod
    def check_otp_rate_limit(phone_number: str) -> None:
        now = time.time()
        window = 3600.0
        hits = [t for t in _otp_hits[phone_number] if now - t < window]
        if len(hits) >= settings.OTP_RATE_LIMIT_PER_HOUR:
            _otp_hits[phone_number] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests, try later",
            )
        hits.append(now)
        _otp_hits[phone_number] = hits

    @staticmethod
    def check_login_rate_limit(identifier: str, client_ip: str | None) -> None:
        """Throttle STAFF login attempts. Shared by /auth/login and /auth/pin-login.

        Two independent buckets per attempt — the claimed identifier and the
        caller's IP — because the two attacks have different shapes:

          * many PINs against one known account  -> caught by the identifier bucket
          * one PIN sprayed across many accounts -> caught by the IP bucket

        Either bucket being full refuses the request, and a refusal does NOT
        consume further budget in the other bucket.

        Counted on every ATTEMPT, not only on failures. Counting failures alone
        lets an attacker reset their own budget with one correct login, and a
        human typing their own PIN does not come close to the cap anyway.

        In-process, like every other limiter here: the real ceiling is this
        number times the worker count, and a restart forgets every bucket. That
        is a known and documented limitation, not a claim of completeness.
        """
        now = time.time()
        window = float(settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        cap = settings.LOGIN_RATE_LIMIT_ATTEMPTS

        keys = [f"user:{(identifier or '').strip().lower()}"]
        if client_ip:
            keys.append(f"ip:{client_ip}")

        pruned: dict[str, list[float]] = {}
        for key in keys:
            hits = [t for t in _login_hits[key] if now - t < window]
            pruned[key] = hits
            if len(hits) >= cap:
                _login_hits[key] = hits
                retry_after = max(1, int(window - (now - hits[0])) + 1)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "too_many_login_attempts",
                        "message": (
                            "Too many sign-in attempts. "
                            f"Try again in about {retry_after} seconds."
                        ),
                        "retry_after_seconds": retry_after,
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        for key, hits in pruned.items():
            hits.append(now)
            _login_hits[key] = hits

    @staticmethod
    def check_test_push_rate_limit(user_id: str) -> None:
        """3 test pushes per minute per staff user.

        Low on purpose. The button exists to answer "does this tablet actually
        receive alerts", which one press settles; a staff member tapping it
        twenty times is either confused or bored, and each press costs an FCM
        send against a shared project quota.
        """
        now = time.time()
        window = 60.0
        key = str(user_id)
        hits = [t for t in _test_push_hits[key] if now - t < window]
        if len(hits) >= 3:
            _test_push_hits[key] = hits
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "too_many_test_pushes",
                    "message": f"Try again in about {retry_after} seconds.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        _test_push_hits[key] = hits

    @staticmethod
    def request_otp(phone_number: str) -> dict:
        CarevoService.check_otp_rate_limit(phone_number)
        # Stub: no SMS actually sent.
        return {"request_id": uuid.uuid4().hex, "stub": True}

    @staticmethod
    async def verify_otp(db: AsyncSession, phone_number: str, otp: str) -> Customer:
        if settings.OTP_STUB_MODE:
            if otp != settings.OTP_STUB_CODE:
                raise HTTPException(status_code=401, detail="Invalid OTP")
        else:
            # No real OTP provider wired yet.
            raise HTTPException(status_code=501, detail="OTP verification not configured")

        res = await db.execute(select(Customer).where(Customer.phone_number == phone_number))
        customer = res.scalars().first()
        if not customer:
            customer = Customer(phone_number=phone_number)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
        return customer

    @staticmethod
    async def verify_firebase_token(
        db: AsyncSession, id_token: str
    ) -> tuple[Customer, bool]:
        """Exchange a verified Firebase phone-auth token for a Customer row.

        Independent of OTP_STUB_MODE: this path never trusts a client-supplied
        code, so it is safe to run with the stub still enabled for dev builds.
        """
        from app.modules.carevo_customer.firebase import (
            find_phone_variants,
            normalize_phone,
            verify_phone_token,
        )

        if not settings.FIREBASE_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Firebase authentication is not enabled on this deployment",
            )

        phone, _uid = await verify_phone_token(id_token)
        canonical = normalize_phone(phone)

        # Match legacy spellings too, so pre-Firebase rows (and their order
        # history) are reused instead of duplicated under the E.164 form.
        res = await db.execute(
            select(Customer).where(Customer.phone_number.in_(find_phone_variants(phone)))
        )
        customer = res.scalars().first()

        created = False
        if not customer:
            customer = Customer(phone_number=canonical)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
            created = True
        elif customer.phone_number != canonical:
            # Upgrade the stored number to E.164 now that it is provider-verified.
            customer.phone_number = canonical
            await db.commit()
            await db.refresh(customer)

        # This path never sets a name (a phone row has no profile to take one
        # from), so `created` changes nothing here today. Returned anyway so
        # both auth routes have the same shape and the app applies one rule.
        return customer, created

    @staticmethod
    async def verify_google_token(
        db: AsyncSession, id_token: str
    ) -> tuple[Customer, bool]:
        """Exchange a verified Firebase Google-provider token for a Customer row.

        Standalone identity: the resulting customer has NO phone number. The app
        renders it as "—" until the customer verifies a phone separately, at
        which point the phone-auth path fills it in on the same row.

        Matching order is google_uid first, then email. The uid is the stable
        key (an email can be reassigned by a Workspace admin); email is the
        fallback that reunites a Google login with a row created by an earlier
        Google sign-in before uid was stored, and backfills the uid onto it.

        Returns `(customer, created)`. `created` distinguishes a SIGNUP from a
        sign-in, which the app needs and cannot work out for itself: on a brand
        new row the `name` below came from the Google profile moments ago, so a
        name the customer typed at sign-in should replace it. On an existing
        row that same name may be one they deliberately chose, and must not be
        overwritten. Both look identical in the response without this flag.
        """
        from app.modules.carevo_customer.firebase import verify_google_token

        if not settings.FIREBASE_ENABLED:
            raise HTTPException(
                status_code=501,
                detail="Firebase authentication is not enabled on this deployment",
            )

        # The third element is the Google profile display name. It is READ and
        # DISCARDED on purpose: `customers.name` is what the customer told US,
        # captured once after signup by the app's name screen and written only
        # by PATCH /customer/me. Nothing else may write that column.
        #
        # Seeding it from the provider is exactly the bug this removes — the
        # row came back with a name the customer never chose, the app had no
        # way to tell it apart from one they did, and the greeting showed the
        # Google name. Keeping the provider out of that field means there is
        # only ever one writer, so there is nothing to arbitrate.
        email, uid, _google_display_name = await verify_google_token(id_token)

        res = await db.execute(select(Customer).where(Customer.google_uid == uid))
        customer = res.scalars().first()

        if not customer:
            res = await db.execute(
                select(Customer).where(func.lower(Customer.email) == email)
            )
            customer = res.scalars().first()

        if not customer:
            # No phone: this is the standalone-identity case the nullable
            # phone_number column (migration 008) exists for.
            #
            # `name` is deliberately NOT copied from the Google profile. See
            # the note on the unpack above: customers.name is the customer's
            # own answer, and seeding it here is what used to make the app
            # greet people by their Google display name.
            customer = Customer(email=email, google_uid=uid)
            db.add(customer)
            await db.commit()
            await db.refresh(customer)
            return customer, True

        # Existing row — reconcile it with what Google just told us.
        changed = False
        if customer.google_uid != uid:
            customer.google_uid = uid
            changed = True
        if customer.email != email:
            customer.email = email
            changed = True
        if changed:
            await db.commit()
            await db.refresh(customer)

        return customer, False

    # --------------------------- Discovery ---------------------------------
    @staticmethod
    def _haversine_km(lat1, lon1, lat2, lon2) -> float:
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return round(2 * r * math.asin(math.sqrt(a)), 3)

    #: Haversine, as a SQL expression, mirroring _haversine_km above term for
    #: term — same earth radius, same asin(sqrt(...)) form. Written out rather
    #: than delegated to PostGIS because PostGIS is NOT installed on this
    #: database (only pgcrypto and plpgsql are; ST_Distance raises
    #: UndefinedObject). Installing it would be a schema change on prod for one
    #: predicate over seven rows.
    #:
    #: The duplication is the point of the comment: the WHERE clause and the
    #: Python annotation MUST agree, or the list would show a distance the
    #: filter disagreed with. If either formula changes, change both.
    _HAVERSINE_SQL = """
        (2 * 6371.0 * asin(sqrt(
             power(sin(radians(CAST(:lat AS double precision) - latitude) / 2), 2)
           + cos(radians(latitude)) * cos(radians(CAST(:lat AS double precision)))
           * power(sin(radians(CAST(:lng AS double precision) - longitude) / 2), 2)
        )))
    """

    # ------------------- city transport modes (030) --------------------------
    @staticmethod
    async def _city_transport_profiles(db: AsyncSession) -> dict[str, dict]:
        """`lower(city name)` -> {city_type, modes: [...]} for every known city.

        One query for the whole outlet list, not one per card.

        ## Absent (city, mode) rows read as the catalog default

        The CROSS JOIN + LEFT JOIN + COALESCE is the rule migration 030 relies
        on instead of a backfill trigger: a city with no row for a mode gets
        `transport_modes.default_enabled`. That makes a city created by ANY code
        path — signup, admin, a hand-written INSERT — behave correctly from the
        moment it exists, with no row required and no second mechanism that has
        to stay in agreement with this one.

        Tolerant of a database that has not run 030 yet: the missing table
        raises, and the except falls back to reading 029's columns. A deploy
        landing before the migration therefore degrades to the OLD behaviour
        rather than serving every city an empty mode list, which would strip
        every chip off the checkout screen.
        """
        try:
            rows = (await db.execute(text("""
                SELECT lower(ci.name) AS key,
                       ci.city_type,
                       m.code, m.label, m.uses_declared_arrival, m.sort_order,
                       COALESCE(ctm.enabled, m.default_enabled) AS enabled
                FROM cities ci
                CROSS JOIN transport_modes m
                LEFT JOIN city_transport_modes ctm
                       ON ctm.city_id = ci.id AND ctm.mode_code = m.code
                WHERE m.is_active = true
                ORDER BY lower(ci.name), m.sort_order
            """))).fetchall()
        except Exception:
            # SAVEPOINT hygiene: a failed statement poisons the surrounding
            # transaction, and this runs mid-request alongside real queries.
            try:
                await db.rollback()
            except Exception:
                pass
            return await CarevoService._city_transport_profiles_legacy(db)

        out: dict[str, dict] = {}
        for r in rows:
            if not r.key:
                continue
            entry = out.setdefault(r.key, {"city_type": r.city_type, "modes": []})
            if r.enabled:
                entry["modes"].append({
                    "code": r.code,
                    "label": r.label,
                    "uses_declared_arrival": bool(r.uses_declared_arrival),
                })
        return out

    @staticmethod
    async def _city_transport_profiles_legacy(db: AsyncSession) -> dict[str, dict]:
        """029-shaped fallback, used only until 030 is applied.

        Synthesises the same `modes` list from the old columns so callers have
        exactly one shape to handle. Tram is absent here by construction: 029
        had no concept of it.
        """
        try:
            rows = (await db.execute(text(
                "SELECT lower(name) AS key, city_type, has_train FROM cities"
            ))).fetchall()
        except Exception:
            try:
                await db.rollback()
            except Exception:
                pass
            return {}

        base = [("walk", "Walk"), ("bike", "Bike"), ("car", "Car"),
                ("auto", "Auto"), ("bus", "Bus")]
        out: dict[str, dict] = {}
        for r in rows:
            if not r.key:
                continue
            modes = [{"code": c, "label": l, "uses_declared_arrival": False}
                     for c, l in base]
            if r.has_train:
                modes.append({"code": "train", "label": "Train",
                              "uses_declared_arrival": True})
            if r.city_type == "metro":
                modes.append({"code": "metro", "label": "Metro",
                              "uses_declared_arrival": True})
            out[r.key] = {"city_type": r.city_type, "modes": modes}
        return out

    @staticmethod
    def _transport_flags(profiles: dict[str, dict], city: Optional[str]) -> dict:
        """The transport fields for one outlet's city.

        `transport_modes` is the real answer as of 030 — the full enabled list,
        each entry carrying whether it is a declared-arrival mode, so an app
        build that has never heard of a given mode still treats it correctly.

        `has_metro` / `has_train` / `city_type` are kept ALONGSIDE it and are
        derived from the same list. They are not redundant: builds already in
        customers' hands read those keys and know nothing about
        `transport_modes`, and one of those builds is the app in production
        right now. Removing them would silently strip Train and Metro from
        every installed app the moment this deploys.

        Returns all-None / empty when the city is unknown. None is NOT False
        here and the distinction is load-bearing: False means "the admin says
        this city has no metro", None means "the server has no opinion", and
        only the second lets the app fall back to its built-in map.
        """
        key = (city or "").strip().lower()
        row = profiles.get(key) if key else None
        if not row:
            return {
                "city_type": None,
                "has_metro": None,
                "has_train": None,
                "transport_modes": None,
            }
        codes = {m["code"] for m in row["modes"]}
        return {
            "city_type": row["city_type"],
            # Derived from the grid, NOT from city_type any more. 029 made
            # "is a metro city" and "offers Metro" the same fact; 030 separates
            # them, and this is the side that means "offers Metro".
            "has_metro": "metro" in codes,
            "has_train": "train" in codes,
            "transport_modes": row["modes"],
        }

    @staticmethod
    async def list_outlets(
        db: AsyncSession,
        lat: Optional[float],
        lng: Optional[float],
        city: Optional[list[str]] = None,
        radius_km: Optional[float] = None,
    ) -> list[dict]:
        """Visible outlets, optionally narrowed to one or more cities.

        `city` became a LIST (was a single string) when the app's city picker
        went multi-select. An empty/None list means "no city filter" — the
        caller decides whether that is reachable; the app disables its CTA
        rather than sending an empty selection.

        `radius_km` filters IN THE QUERY, not after it. It needs lat/lng — a
        radius with no origin has no meaning, so it is ignored without one
        rather than guessing an origin or returning nothing.

        City and radius are INDEPENDENT and AND together when both are given.
        The app sends only one at a time (radius in Near Me / Travel, cities
        when the customer picks them), but that is the app's product decision
        and is deliberately NOT enforced here — a server that rejected the
        combination would be inventing a rule the data does not have, and
        "outlets in Chennai within 20km" is a perfectly coherent question.
        """
        # Normalised here rather than at the edge so every caller gets the same
        # treatment: blanks dropped, lowercased once for the comparison below.
        cities = [c.strip().lower() for c in (city or []) if c and c.strip()]


        rows = (await db.execute(text(
            "SELECT id, location_name, city, locality, latitude, longitude, upi_id, image_url, "
            "       phone_number, created_at, opens_at, closes_at, is_manually_closed, "
            # Payment methods (034), SELECTed with the row rather than resolved
            # per outlet. payment_methods_for is one query per call, which on
            # the discovery list would be N round trips on the first screen the
            # customer sees — the same reason the offer summary and the city
            # transport profiles above are each one query for the whole list.
            "       payment_prepaid_enabled, payment_pay_at_pickup_enabled, "
            "       payment_upi_manual_enabled, cashfree_unlocked "
            "FROM outlets "
            "WHERE is_visible = true AND deactivated_at IS NULL "
            # `= ANY(array)` rather than an IN-list built by string
            # interpolation: one bound parameter, no injection surface, and it
            # works unchanged for one city or ten.
            #
            # CAST for the same reason as list_outlets in carevo_admin: with a
            # NULL/empty bind Postgres cannot infer the parameter type from the
            # comparison alone. Case-insensitive on both sides so a city picked
            # from /customer/areas matches regardless of stored capitalisation.
            "  AND (CAST(:cities AS varchar[]) IS NULL "
            "       OR cardinality(CAST(:cities AS varchar[])) = 0 "
            "       OR lower(city) = ANY(CAST(:cities AS varchar[])))"
            # Radius, applied HERE rather than to the annotated list below.
            # Filtering after the fetch would still pull every row and only
            # hide some — fine at seven outlets, wrong as a shape.
            #
            # An outlet with no pin (latitude/longitude NULL) is excluded when
            # a radius is asked for: its distance is unknowable, and silently
            # including it would put an outlet of unknown distance inside a
            # circle the customer explicitly drew.
            "  AND (CAST(:radius_km AS double precision) IS NULL "
            "       OR (latitude IS NOT NULL AND longitude IS NOT NULL "
            "           AND " + CarevoService._HAVERSINE_SQL +
            "               <= CAST(:radius_km AS double precision)))"
        ), {
            "cities": cities or None,
            # Only a radius WITH an origin is a filter. Without lat/lng the
            # expression has nothing to measure from, so it is dropped.
            "radius_km": radius_km if (lat is not None and lng is not None) else None,
            "lat": lat,
            "lng": lng,
        })).fetchall()

        # Offer summary for the inline chip (migration 016). ONE query for the
        # whole list — a per-card lookup would be N round trips on the first
        # screen the customer sees. "*" holds the platform-wide campaigns, which
        # reach every outlet including those with no offer of their own.
        offers = await PromotionService.offer_summary_by_outlet(db)
        platform = offers.get("*")

        # Transport profile per city (migration 029). Also ONE query, for the
        # same reason as offers above, and keyed lower() on both sides because
        # `outlets.city` is free text with no FK — see migration 013.
        city_profiles = await CarevoService._city_transport_profiles(db)

        # Whether a checkout can be opened at all — a deployment property, not
        # an outlet one, so it is asked once for the whole list. See
        # _gateway_can_charge for why this is not `is_live`.
        gateway_live = _gateway_can_charge()

        out = []
        for r in rows:
            (oid, name, city, locality, o_lat, o_lng, upi_id, image_url,
             phone_number, created_at, opens_at, closes_at,
             is_manually_closed, prepaid_enabled, pickup_enabled,
             upi_enabled, cashfree_unlocked) = r
            distance = None
            if lat is not None and lng is not None and o_lat is not None and o_lng is not None:
                distance = CarevoService._haversine_km(lat, lng, float(o_lat), float(o_lng))
            summary = offers.get(str(oid)) or platform
            # Operating-hours status (migration 024), computed server-side from
            # the SAME function that gates order creation, so the card's label
            # and the order gate can never disagree.
            avail = CarevoService.outlet_availability(
                opens_at, closes_at, bool(is_manually_closed))
            out.append({
                "id": oid,
                "name": name,
                # The fullest address this schema holds. `outlets` has no
                # street-address column at all — locality (migration 012) and
                # city are the whole of it — so "Koramangala, Bengaluru" IS the
                # full address, not a truncation of one. Joined here rather than
                # in each app so both clients read the same string.
                #
                # Falls back to whichever part exists: outlets predating 012
                # have no locality and must still render their city.
                "address": ", ".join(p for p in (locality, city) if p) or None,
                # is_open kept for the existing client contract, but now REAL
                # (was hardcoded True): true only when orders are accepted.
                # order_status carries the three-state label the app shows;
                # opening_time/closing_time back its "9:00 AM – 10:00 PM" line.
                "is_open": avail["status"] == AVAIL_OPEN,
                "order_status": avail["status"],
                "closed_reason": avail["reason"],
                "opening_time": opens_at.strftime("%H:%M") if opens_at else None,
                "closing_time": closes_at.strftime("%H:%M") if closes_at else None,
                "distance_km": distance,
                "upi_id": upi_id,
                "image_url": image_url,
                "locality": locality,
                # Also emitted on its own, not only folded into `address`
                # above — behaviour (which transport modes to offer) is keyed
                # off this, and keying it off a display string would break on
                # pre-012 outlets whose `address` has no comma to split.
                "city": city,
                # Migration 029. The SERVER's answer to "which travel modes does
                # this city support", so a new metro city needs an admin toggle
                # rather than an app release. All three are None/absent when the
                # city has no `cities` row, which the app reads as "no answer"
                # and falls back to its built-in map — absent still means safe.
                **CarevoService._transport_flags(city_profiles, city),
                # Normalised to None so an empty string never renders a call
                # button that dials nothing.
                "phone_number": (phone_number or "").strip() or None,
                # float() because the column is `numeric` -> Decimal, which
                # would serialise as a JSON string and break the Maps URL.
                "latitude": float(o_lat) if o_lat is not None else None,
                "longitude": float(o_lng) if o_lng is not None else None,
                "offer_count": (summary or {}).get("count", 0),
                "offer_text": (summary or {}).get("text"),
                # Payment methods (034). CAPABILITY ONLY on this endpoint — no
                # customer-specific gate is applied, so pay-at-pickup appearing
                # here means "this outlet offers it", not "you may use it". The
                # menu endpoint and POST /orders both resolve it against the
                # actual caller. Kept in the same order payment_methods_for
                # produces so the app never has to sort it.
                # Prepaid needs the owner flag AND the platform unlock AND a
                # gateway (035) — see payment_methods_for, which this mirrors
                # for the list case. Kept inline rather than calling that
                # function per row: it is one query per call, which on the
                # first screen the customer sees would be N round trips.
                "payment_methods": (
                    ([PAY_PREPAID]
                     if (prepaid_enabled and cashfree_unlocked and gateway_live)
                     else [])
                    + ([PAY_AT_PICKUP] if pickup_enabled else [])
                    + ([PAY_UPI_MANUAL] if upi_enabled else [])
                ),
                # Backs the app's "Newest" sort. Real column, not a proxy —
                # sorting by it is the outlet's actual join date, so the label
                # means what it says.
                "created_at": created_at,
            })
        if lat is not None and lng is not None:
            out.sort(key=lambda x: (x["distance_km"] is None, x["distance_km"] or 0))
        return out

    # ------------------------------ Menu -----------------------------------
    @staticmethod
    async def get_menu(
        db: AsyncSession, outlet_id: uuid.UUID,
        customer: Optional[Customer] = None,
    ) -> dict:
        """The outlet's latest menu, plus what it can be paid with.

        `customer` is optional and additive (034): passed, the payment_methods
        list reflects THAT customer's eligibility for pay-at-pickup; omitted,
        it is the outlet's capability only. The controller always passes one —
        this endpoint is behind get_current_customer — so the default exists
        for internal callers and tests rather than for the route.
        """
        # STOCK (033): reclaim lapsed holds BEFORE reading availability.
        #
        # This is the frequently-hit customer read and the one place a stale
        # hold does visible damage: reserve_for_order flips is_available to
        # false when stock hits zero, so somebody's abandoned cart makes a dish
        # read "sold out" to every other customer until the hold lapses. The
        # sweep gives the units back and restores is_available, so the menu
        # below reflects what is genuinely orderable.
        #
        # Check-on-read by design — there is no worker. _expire_stale_pickups
        # is wired the same way for the same reason, and the sweep is
        # idempotent, so being called on every menu load costs one UPDATE that
        # matches nothing in the normal case.
        #
        # Best-effort: a failure here must not take down the menu, which is the
        # app's main screen. A missed sweep self-heals on the next read.
        from app.modules.carevo_customer.stock import StockService
        try:
            await StockService.sweep_expired(db, outlet_id=outlet_id)
        except Exception:
            logger.warning("stock sweep failed during get_menu for outlet %s",
                           outlet_id, exc_info=True)
            await db.rollback()

        # Categories of the latest menu for this outlet.
        #
        # `is_active` still filters (a deleted item should not exist for the
        # customer at all), but `is_available` NO LONGER DOES: temporarily
        # sold-out items are returned with `is_available: false` so the app can
        # render them as greyed, non-orderable placeholders.
        #
        # Hiding them outright was worse than it looked. A regular who is
        # scanning for their usual dish cannot tell "sold out today" from
        # "taken off the menu" from "I'm on the wrong restaurant" — the row is
        # simply absent, and absence has no explanation attached to it.
        #
        # This does NOT make an unavailable item orderable. check_cart_availability
        # and create_order both re-check the flag server-side, and the app
        # refuses to add these to the cart.
        rows = (await db.execute(text("""
            SELECT c.id AS cat_id, c.name AS cat_name,
                   mi.id AS item_id, mi.name AS item_name, mi.base_price,
                   mi.is_veg, mi.is_available, mi.prep_time_minutes, mi.tags,
                   mi.image_url
            FROM categories c
            JOIN menus m ON m.id = c.menu_id
            LEFT JOIN menu_items mi
                   ON mi.category_id = c.id
                  AND mi.is_active = true
            WHERE m.outlet_id = :oid AND m.is_latest = true
            ORDER BY c.name, mi.name
        """), {"oid": str(outlet_id)})).fetchall()

        # modifiers per item for customizations
        item_ids = [r.item_id for r in rows if r.item_id is not None]
        mods: dict = defaultdict(list)
        if item_ids:
            mrows = (await db.execute(text("""
                SELECT menu_item_id, modifier_name FROM item_modifiers
                WHERE menu_item_id = ANY(:ids)
            """), {"ids": [str(i) for i in item_ids]})).fetchall()
            for mr in mrows:
                mods[str(mr.menu_item_id)].append(mr.modifier_name)

        cats: dict = {}
        order: list = []
        for r in rows:
            key = str(r.cat_id)
            if key not in cats:
                cats[key] = {"id": r.cat_id, "name": r.cat_name, "items": []}
                order.append(key)
            if r.item_id is not None:
                cats[key]["items"].append({
                    "id": r.item_id,
                    "name": r.item_name,
                    "base_price": float(r.base_price) if r.base_price is not None else 0.0,
                    "is_veg": bool(r.is_veg),
                    "is_available": bool(r.is_available),
                    "prep_time_minutes": r.prep_time_minutes,
                    "image_url": r.image_url,
                    "tags": r.tags,
                    "customizations": mods.get(str(r.item_id), []),
                })
        phone = (await db.execute(text(
            "SELECT phone_number FROM outlets WHERE id = :o"), {"o": str(outlet_id)})).scalar()
        return {
            "outlet_id": outlet_id,
            "outlet_phone_number": (phone or "").strip() or None,
            # Payment methods (034), resolved for THIS customer when there is
            # one. This is the list checkout should render.
            "payment_methods": await CarevoService.payment_methods_for(
                db, outlet_id, customer),
            "categories": [cats[k] for k in order],
        }

    @staticmethod
    def outlet_availability(opens_at, closes_at, is_manually_closed, *, now=None) -> dict:
        """Current order availability for an outlet.

        Returns {"status": AVAIL_*, "reason": str|None}. Pure and
        clock-injectable (`now` is a tz-aware datetime), so it is directly
        testable without waiting for real time. This is the SINGLE source of
        truth: the same function decides what the customer is shown AND whether
        a new order is accepted, so display and gate can never disagree.

        Rules:
          - is_manually_closed                 -> closed (temporarily closed)
          - no schedule (either time is NULL)  -> open (backward compatible:
            every existing outlet has NULL hours and must keep accepting orders)
          - before opens_at, or at/after closes_at -> closed
          - within ORDER_CUTOFF_MINUTES of closes_at -> closing_soon
          - otherwise                          -> open
        Handles an overnight window (closes_at <= opens_at, e.g. 18:00->02:00).
        """
        if is_manually_closed:
            return {"status": AVAIL_CLOSED, "reason":
                    "This outlet is temporarily closed and is not taking "
                    "orders right now."}
        if opens_at is None or closes_at is None:
            return {"status": AVAIL_OPEN, "reason": None}

        now = now or datetime.now(_OUTLET_TZ)
        n = now.hour * 60 + now.minute
        o = opens_at.hour * 60 + opens_at.minute
        c = closes_at.hour * 60 + closes_at.minute

        # Is `n` inside [o, c)? c <= o means the window wraps past midnight.
        is_open_now = (o <= n < c) if o < c else (n >= o or n < c)
        if not is_open_now:
            return {"status": AVAIL_CLOSED,
                    "reason": "This outlet is closed right now."}

        mins_to_close = (c - n) % (24 * 60)
        if mins_to_close <= ORDER_CUTOFF_MINUTES:
            return {"status": AVAIL_CLOSING_SOON, "reason":
                    "This outlet is closing soon and is not accepting new "
                    "orders."}
        return {"status": AVAIL_OPEN, "reason": None}

    # ------------------- Arrival feasibility (migration 031) ----------------
    @staticmethod
    def _normalise_requested_pickup(value: Optional[datetime]) -> Optional[datetime]:
        """The customer's chosen pickup time as tz-aware UTC, or None for ASAP.

        A NAIVE datetime is read as UTC rather than rejected. Pydantic accepts
        both an offset-bearing ISO string and a bare one, and the app sends the
        former — but a bare value reaching here and being silently treated as
        IST (or as the server's local clock) is precisely the class of bug the
        ORDER_CUTOFF comment warns about. UTC is the project's wire convention
        for every other timestamp on this model, so it is the honest reading.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    async def _estimated_arrival_at(
        db: AsyncSession, *, outlet_id, outlet_lat, outlet_lng,
        transport_mode, origin_lat, origin_lng, declared_arrival_at,
        requested_pickup_at, now: Optional[datetime] = None,
    ) -> tuple[datetime, str]:
        """When this customer is expected at the counter, and where that came from.

        ONE answer for every mode, because PredictionService.predict_travel
        already unifies them: it returns "seconds until this customer gets
        here" whether that came from a declared train/metro arrival
        (`customer_declared`, arrival + platform-to-door), a real Distance
        Matrix ETA (`maps_live` / `maps_cached`), or distance/speed over
        MODE_SPEED_MPS (`haversine_fallback`). Nothing new is computed here and
        no second travel model is introduced — this only turns a duration into
        an instant.

        A SCHEDULED order short-circuits: the customer named the time, so there
        is nothing to estimate and no reason to spend a Maps call on it.

        Best-effort by construction. predict_travel never raises for a missing
        origin — it returns a deliberately wide 20-minute fallback (FR-C6, the
        location-denied case) — so a customer who refused GPS is gated on a
        generous estimate rather than being refused outright.
        """
        now = now or datetime.now(timezone.utc)
        if requested_pickup_at is not None:
            return requested_pickup_at, "scheduled"

        from app.modules.prediction.service import PredictionService
        mu_travel, _sigma, source = await PredictionService.predict_travel(
            db, outlet_id, origin_lat, origin_lng, outlet_lat, outlet_lng,
            transport_mode, declared_arrival_at=declared_arrival_at)
        return now + timedelta(seconds=float(mu_travel)), source

    @staticmethod
    async def _estimate_prep_seconds(db: AsyncSession, items) -> int:
        """Best prep-time estimate available AT ORDER CREATION, before any
        row exists — the twin's mu_ready_s (service.py's _recompute_twin)
        is not an option here: it is seeded FROM a committed order and
        recomputed after payment, so nothing upstream of create_order can
        read it.

        Uses menu_items.prep_time_minutes, the same per-item figure the
        kitchen display and get_menu already show (service.py:930,966) — the
        SLOWEST ordered item, not the sum, because items are prepared in
        parallel on the same ticket and the order cannot leave before its
        slowest component does. An item with no timing data on file falls
        back to DEFAULT_PREP_MINUTES_IF_UNKNOWN rather than silently
        contributing zero.
        """
        item_ids = [str(i.menu_item_id) for i in items]
        if not item_ids:
            return DEFAULT_PREP_MINUTES_IF_UNKNOWN * 60
        minutes = await db.scalar(text(
            "SELECT MAX(COALESCE(prep_time_minutes, :d)) "
            "FROM menu_items WHERE id = ANY(:ids)"),
            {"ids": item_ids, "d": DEFAULT_PREP_MINUTES_IF_UNKNOWN})
        return int(minutes or DEFAULT_PREP_MINUTES_IF_UNKNOWN) * 60

    @staticmethod
    async def _assert_scheduled_release_feasible(
        db: AsyncSession, *, outlet_id, items, requested_pickup_at,
        now: Optional[datetime] = None,
    ) -> None:
        """Refuse a scheduled pickup too close to be realistically cooked.

        Instant orders are UNCHANGED — this only runs when the customer
        named a time. Feasible iff:

            requested_pickup_at - now
                >= estimated_prep_s + acceptance_timeout_s
                   + SCHEDULED_RELEASE_SAFETY_MARGIN_S

        acceptance_timeout_s is read per-outlet (the same column
        AcceptanceService reads, acceptance.py:96) because a manual-
        acceptance outlet can spend that whole window before anyone taps
        Accept — prep has not even started yet at that point, so leaving it
        out would let a feasible-looking slot actually be impossible at a
        slow-to-accept restaurant.

        Raises 409 with the earliest allowed pickup instant in the body, so
        the app can offer it directly rather than making the customer guess.
        """
        if requested_pickup_at is None:
            return
        now = now or datetime.now(timezone.utc)

        # Reuses prediction/service.py's ONE margin knob rather than adding a
        # second one with the same name and a different value — see that
        # module for why it is not tuned per call site.
        from app.modules.prediction.service import SCHEDULED_RELEASE_SAFETY_MARGIN_S

        prep_s = await CarevoService._estimate_prep_seconds(db, items)
        timeout_s = await db.scalar(text(
            "SELECT acceptance_timeout_s FROM outlets WHERE id = :oid"),
            {"oid": str(outlet_id)}) or 0

        required_s = prep_s + int(timeout_s) + SCHEDULED_RELEASE_SAFETY_MARGIN_S
        earliest = now + timedelta(seconds=required_s)
        if requested_pickup_at < earliest:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SCHEDULED_PICKUP_TOO_SOON",
                    "message": (
                        "This restaurant needs more time to prepare your "
                        "order. Please choose a later pickup time."
                    ),
                    "earliest_pickup_at": earliest.isoformat(),
                },
            )

    @staticmethod
    async def _assert_arrival_feasible(
        db: AsyncSession, *, gate, outlet_id, transport_mode, origin_lat,
        origin_lng, declared_arrival_at, requested_pickup_at,
        now: Optional[datetime] = None,
    ) -> dict:
        """Refuse an order whose customer cannot realistically be served.

        Applies to EVERY mode — declared-arrival, GPS-estimated, and scheduled —
        because the question is the same one in all three cases: will this
        restaurant still be open, with room to cook, when this person arrives?
        Before this existed only the "can they take an order right now" half was
        checked, so a customer 40 minutes away could pay for food from a kitchen
        that shuts in 35.

        Evaluated with outlet_availability REUSED VERBATIM, given the arrival
        instant as its injectable `now`. That is the whole point of the function
        being pure and clock-injectable, and it means the scheduled gate and the
        immediate gate can never drift apart into two different definitions of
        "open enough" — including the 30-minute pre-close cutoff, which is
        already exactly "is there room to cook this".

        Raises 409 with ARRIVAL_INFEASIBLE_MESSAGE. Returns the estimate on
        success so the caller can record what it decided on.
        """
        now = now or datetime.now(timezone.utc)

        # Horizon checks first: cheapest, and they protect the availability call
        # below from a request so far out that minute-of-day wraps (see
        # SCHEDULED_MAX_AHEAD_S). A time already past is refused for the obvious
        # reason — nothing can be cooked for it.
        if requested_pickup_at is not None:
            ahead = (requested_pickup_at - now).total_seconds()
            if ahead <= 0 or ahead > SCHEDULED_MAX_AHEAD_S:
                raise HTTPException(status_code=409,
                                    detail=ARRIVAL_INFEASIBLE_MESSAGE)

        arrival_at, source = await CarevoService._estimated_arrival_at(
            db, outlet_id=outlet_id,
            outlet_lat=gate.latitude, outlet_lng=gate.longitude,
            transport_mode=transport_mode, origin_lat=origin_lat,
            origin_lng=origin_lng, declared_arrival_at=declared_arrival_at,
            requested_pickup_at=requested_pickup_at, now=now)

        # IST, never UTC. outlet_availability reads hour/minute off whatever it
        # is handed and opens_at/closes_at are bare LOCAL times, so a UTC
        # instant would be compared against the wrong clock — the same trap
        # documented on ORDER_CUTOFF_MINUTES.
        avail = CarevoService.outlet_availability(
            gate.opens_at, gate.closes_at, bool(gate.is_manually_closed),
            now=arrival_at.astimezone(_OUTLET_TZ))
        if avail["status"] != AVAIL_OPEN:
            raise HTTPException(status_code=409,
                                detail=ARRIVAL_INFEASIBLE_MESSAGE)
        return {"arrival_at": arrival_at, "source": source,
                "availability": avail["status"]}

    # --------------------- Payment methods (migration 034) ------------------
    @staticmethod
    async def payment_methods_for(
        db: AsyncSession, outlet_id, customer: Optional[Customer] = None
    ) -> list[str]:
        """Which payment methods this outlet can offer THIS customer, in order.

        THE one place that decision is made. create_order refuses anything this
        does not return, and the customer app renders exactly this list, so the
        two can never disagree about what is on offer.

        Read with raw SQL because the 034 outlet columns are deliberately not
        mapped on the Outlet model — see the migration header.

        PREPAID requires the flag AND a usable gateway — see
        _gateway_can_charge, which is deliberately NOT `is_live`. The flag
        alone cannot conjure a payment provider, so switching Cashfree off
        deployment-wide removes prepaid from every outlet's list no matter what
        the column says. That is also why the empty list is a REAL outcome and
        not a bug: an outlet that is prepaid-only on a deployment with no
        gateway can take no orders, and the honest thing is to say so rather
        than to offer a method that will fail at checkout.

        PAY_AT_PICKUP requires the flag AND three things about the customer:

          * a VERIFIED PHONE. The restaurant is about to cook on the strength
            of that number, and `customers.phone_number` is only ever set by a
            verified sign-in — a Google-only account has none (migration 008),
            so it is offered prepaid instead.
          * NO OPEN UNPAID PICKUP ORDER. The abuse cap, global rather than
            per-outlet; see _assert_no_open_pickup_order.
          * FEWER THAN NO_SHOW_STRIKE_LIMIT no-shows.

        `customer` is optional so the discovery endpoints can ask what an
        outlet is CAPABLE of without a customer in hand. With no customer the
        customer-specific gates are skipped, which means the list is an upper
        bound; create_order re-resolves WITH the customer and is the authority.
        """
        row = (await db.execute(text("""
            SELECT payment_prepaid_enabled, payment_pay_at_pickup_enabled,
                   payment_upi_manual_enabled, cashfree_unlocked
              FROM outlets WHERE id = :oid
        """), {"oid": str(outlet_id)})).first()
        if row is None:
            return []

        prepaid_on, pickup_on, upi_on, cashfree_unlocked = (
            bool(row[0]), bool(row[1]), bool(row[2]), bool(row[3]))

        # CASHFREE_ONLY (config.py): Cashfree prepaid is the only path the
        # platform offers at all, full stop. Short-circuits before pickup/upi
        # are even considered, so an outlet that has pay-at-pickup or UPI
        # flags left on from before the cutover still gets nothing but
        # PREPAID — or nothing, if it isn't unlocked. Default false; this
        # branch is unreachable until the switch is set.
        if settings.CASHFREE_ONLY:
            return ([PAY_PREPAID]
                    if prepaid_on and cashfree_unlocked and _gateway_can_charge()
                    else [])

        methods: list[str] = []

        # PREPAID needs THREE yeses, and they are three different parties
        # saying different things (migration 035):
        #   payment_prepaid_enabled — the OWNER wants to offer it
        #   cashfree_unlocked       — CAREVO permits it for this outlet
        #   _gateway_can_charge()   — the DEPLOYMENT has a gateway selected
        # Any one of them off withdraws the method. Keeping them separate is
        # what lets the owner app render "you have it off" and "we have it
        # locked" as different states instead of one unexplained absence.
        if prepaid_on and cashfree_unlocked and _gateway_can_charge():
            methods.append(PAY_PREPAID)

        # Both customer-side methods need a VERIFIED PHONE, and for the same
        # reason: the restaurant is going to ring them (pay-at-pickup) or has
        # to be able to chase a payment that did not arrive (direct UPI). A
        # Google-only account has no phone (migration 008) and is offered
        # prepaid instead.
        has_phone = (customer is not None
                     and bool((customer.phone_number or "").strip()))

        if pickup_on:
            if customer is None:
                # CAPABILITY ONLY — the discovery list has no customer, so it
                # reports what the outlet offers, not what this person may use.
                methods.append(PAY_AT_PICKUP)
            elif has_phone:
                blocked = await CarevoService._open_pickup_order_id(db, customer)
                strikes = await CarevoService._no_show_count(db, customer)
                if blocked is None and strikes < NO_SHOW_STRIKE_LIMIT:
                    methods.append(PAY_AT_PICKUP)

        # UPI_MANUAL (035). The outlet flag already implies a VPA, a payee name
        # and an attestation — ck_outlets_upi_manual_requires_vpa makes that a
        # database fact, so this does not re-check them.
        #
        # The customer gate is false_claim_count, NOT no_show_count: a direct
        # UPI order is paid before the kitchen starts, so there is no food to
        # waste by not turning up. What it risks instead is somebody claiming a
        # payment they never sent, which is what that counter records.
        if upi_on:
            if customer is None:
                methods.append(PAY_UPI_MANUAL)
            elif has_phone:
                claims = await CarevoService._false_claim_count(db, customer)
                if claims < FALSE_CLAIM_STRIKE_LIMIT:
                    methods.append(PAY_UPI_MANUAL)

        return methods

    @staticmethod
    async def _would_offer_anything(
        db: AsyncSession, outlet_id, *, prepaid: bool, pickup: bool, upi: bool
    ) -> bool:
        """Would these flags leave a customer able to order at all?

        Asks the RESOLVER rather than re-deriving its rule, so the check cannot
        drift from the thing it is checking. The outlet's unlock and the
        deployment's gateway are read from their real sources; only the three
        flags are hypothetical.

        No customer is passed, so this is the outlet's capability — which is
        the right question for a settings save: a per-customer gate (a
        no-show strike, an open order) must not stop an owner configuring their
        restaurant.
        """
        if pickup or upi:
            return True
        if not prepaid:
            return False
        # Prepaid-only: it lands iff the platform permits it AND a gateway is
        # selected on this deployment.
        unlocked = await db.scalar(text(
            "SELECT cashfree_unlocked FROM outlets WHERE id = :oid"),
            {"oid": str(outlet_id)})
        return bool(unlocked) and _gateway_can_charge()

    @staticmethod
    async def _false_claim_count(db: AsyncSession, customer: Customer) -> int:
        """This customer's false-payment-claim strikes. Raw SQL — 035 unmapped."""
        n = await db.scalar(text(
            "SELECT false_claim_count FROM customers WHERE id = :cid"),
            {"cid": str(customer.id)})
        return int(n or 0)

    @staticmethod
    async def _no_show_count(db: AsyncSession, customer: Customer) -> int:
        """This customer's no-show strikes. Raw SQL — 034 is unmapped."""
        n = await db.scalar(text(
            "SELECT no_show_count FROM customers WHERE id = :cid"),
            {"cid": str(customer.id)})
        return int(n or 0)

    @staticmethod
    async def _open_pickup_order_id(
        db: AsyncSession, customer: Customer, *, exclude_order_id=None
    ) -> Optional[str]:
        """This customer's open unpaid pay-at-pickup order, if they have one.

        THE ABUSE CAP, and deliberately GLOBAL rather than per-outlet. The
        existing hoarding cap in create_order is per-customer-per-outlet and
        joins stock_reservations, which means it only bites when at least one
        item is stock-TRACKED (reserve_for_order skips untracked items
        entirely). Neither property is right here: what is being protected is
        not one restaurant's stock but the platform's exposure to somebody who
        orders food and never pays for it, and they could do that at five
        outlets at once.

        Terminal orders are excluded, so a cancelled or collected order never
        blocks the next one. PAID is excluded too — once the money is in, the
        customer is free to order again immediately.
        """
        # BOTH non-gateway modes count toward the one cap (035). The exposure
        # is a person holding food they have not paid for, and which of the two
        # buttons they pressed makes no difference to that.
        # SWEEP THIS CUSTOMER'S OWN LAPSED UPI ORDERS FIRST (review fix).
        #
        # The cap is global, so an abandoned direct-UPI order at outlet A
        # blocked the same customer ordering at outlet B. The only thing that
        # cancelled it was expire_unclaimed_upi_orders on outlet A's staff
        # poll — so the customer was locked out until a restaurant they had
        # walked away from happened to open its tablet. At a quiet outlet, or
        # one closed for the night, that is indefinite.
        #
        # Swept per-CUSTOMER rather than per-outlet here, which is both the
        # narrowest scope that fixes it and the one the caller already has.
        # Best-effort: the cap must still be enforced if the sweep fails, so a
        # failure here leaves the stricter answer rather than no answer.
        try:
            await CarevoService.expire_unclaimed_upi_orders(
                db, customer_id=customer.id)
        except Exception:
            logger.warning(
                "self-service UPI sweep failed for customer %s; the open-order "
                "cap may hold a lapsed order", customer.id, exc_info=True)
            await db.rollback()

        clauses = [
            "customer_id = :cid",
            "payment_mode = ANY(:modes)",
            "payment_status <> 'PAID'",
            "upper(coalesce(status, '')) <> ALL(:terminal)",
        ]
        params: dict = {
            "cid": str(customer.id),
            "modes": list(_NON_GATEWAY_METHODS),
            "terminal": list(_TERMINAL_STATUSES),
        }
        if exclude_order_id is not None:
            clauses.append("id <> :self_id")
            params["self_id"] = str(exclude_order_id)

        row = (await db.execute(text(
            "SELECT id FROM customer_orders WHERE " + " AND ".join(clauses)
            + " LIMIT 1"
        ), params)).first()
        return str(row[0]) if row else None

    @staticmethod
    async def _resolve_payment_method(
        db: AsyncSession, customer: Customer, outlet_id, requested: Optional[str]
    ) -> str:
        """Settle which method this order uses, or refuse with a 409.

        Runs BEFORE any row is written — see the call site in create_order.

        `requested=None` means PREPAID, and that is the whole backwards
        compatibility story: an already-installed customer_app build has no
        `payment_method` field to send, so it implicitly asks for prepaid. At a
        pay-at-pickup-only outlet that is refused here, with prose the app
        renders verbatim out of `detail["message"]` — no order row is created,
        nothing is held, and the customer is told to update rather than being
        dropped onto a payment screen that cannot work.
        """
        available = await CarevoService.payment_methods_for(db, outlet_id, customer)
        wanted = (requested or PAY_PREPAID).upper()

        if wanted in available:
            return wanted

        # The refusal prose is chosen by WHY it was refused, because the three
        # reasons have three different remedies and a single message would be
        # wrong for two of them.
        if wanted == PAY_AT_PICKUP:
            if not (customer.phone_number or "").strip():
                message = ("Pay at pickup needs a verified mobile number. "
                           "Add one to your account to use it.")
            elif (open_id := await CarevoService._open_pickup_order_id(
                    db, customer)) is not None:
                # ITS OWN ERROR CODE, not the generic one.
                #
                # This is the only refusal reason the app can ACT on beyond
                # reading the message: there is a specific order blocking this
                # one, and the app should be able to deep-link straight to it.
                # Folding it into PAYMENT_METHOD_UNAVAILABLE would drop the id
                # and leave the customer to go and find the order themselves.
                #
                # Mirrors the existing UNPAID_ORDER_PENDING contract exactly —
                # same shape, same reason, and the id stays out of the prose
                # because a uuid is not something to show anybody.
                #
                # Raised HERE as well as in create_order because this gate
                # notices first: at a pickup-only outlet an open order empties
                # the available list, so the generic branch below would
                # otherwise claim the restaurant was not taking orders.
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "OPEN_PICKUP_ORDER_PENDING",
                        "order_id": open_id,
                        "message": (
                            "You already have an order waiting to be "
                            "collected. Pick that one up first."
                        ),
                    },
                )
            elif await CarevoService._no_show_count(db, customer) >= NO_SHOW_STRIKE_LIMIT:
                message = ("Pay at pickup is not available on your account. "
                           "You can still pay online.")
            else:
                message = ("This restaurant is not taking pay-at-pickup orders "
                           "right now.")
        elif wanted == PAY_UPI_MANUAL:
            # Same shape as the pay-at-pickup branch: the reason decides the
            # prose, because the three reasons have three different remedies.
            if not (customer.phone_number or "").strip():
                message = ("Paying by UPI needs a verified mobile number. "
                           "Add one to your account to use it.")
            elif await CarevoService._false_claim_count(
                    db, customer) >= FALSE_CLAIM_STRIKE_LIMIT:
                message = ("Paying directly by UPI is not available on your "
                           "account. You can still pay online.")
            else:
                message = ("This restaurant is not taking direct UPI payments "
                           "right now.")
        elif PAY_AT_PICKUP in available or PAY_UPI_MANUAL in available:
            message = ("This restaurant now takes payment when you collect. "
                       "Please update Gusto Skip to place this order.")
        else:
            message = ("This restaurant is not taking orders right now. "
                       "Please try again shortly.")

        raise HTTPException(
            status_code=409,
            detail={
                "error": "PAYMENT_METHOD_UNAVAILABLE",
                # DATA for the app: what it MAY use instead. An app that knows
                # about pay-at-pickup can re-offer it without another round
                # trip; one that does not simply ignores the field.
                "available": available,
                "message": message,
            },
        )

    # ----------------------------- Orders ----------------------------------
    @staticmethod
    async def create_order(db: AsyncSession, customer: Customer, payload) -> dict:
        # Operating-hours / manual-closure gate (migration 024). Checked FIRST,
        # before any row is written, so a closed outlet never leaves an orphan
        # CREATED order behind. Only NEW orders are gated here — nothing touches
        # orders already in progress.
        #
        # latitude/longitude joined in for the arrival estimate below; they were
        # always on this row and cost nothing to carry.
        gate = (await db.execute(text(
            "SELECT opens_at, closes_at, is_manually_closed, latitude, longitude "
            "FROM outlets WHERE id = :oid"
        ), {"oid": str(payload.outlet_id)})).first()
        if gate is None:
            raise HTTPException(status_code=404, detail="Outlet not found")

        # PAYMENT METHOD (migration 034), resolved FIRST — before the hours
        # gate, before the arrival gate, before any row is written.
        #
        # Position is deliberate. This is the only gate whose refusal means
        # "this app cannot place this order at all", and the customer's remedy
        # (update the app, or prepay) does not change with the shop's opening
        # hours. Telling someone the kitchen is closed when the real problem is
        # that their build cannot pay would send them back at 7pm to be refused
        # again for a different reason.
        #
        # Raises 409 PAYMENT_METHOD_UNAVAILABLE. Nothing is committed, nothing
        # is held, no gateway order exists — identical in that respect to the
        # gateway-failure paths further down.
        payment_mode = await CarevoService._resolve_payment_method(
            db, customer, payload.outlet_id,
            getattr(payload, "payment_method", None))
        pay_at_pickup = payment_mode == PAY_AT_PICKUP
        upi_manual = payment_mode == PAY_UPI_MANUAL
        # Everything the two non-gateway paths share: no gateway call, a
        # contact snapshot, no scheduling, and the open-order cap.
        non_gateway = payment_mode in _NON_GATEWAY_METHODS

        # SCHEDULED PICKUP IS NOT AVAILABLE FOR PAY AT PICKUP (migration 034).
        #
        # Refused rather than quietly accepted, because quietly accepted is
        # what it was: `requested_pickup_at` is stored on the row and the
        # arrival gate judges it, but `release_at` — the column that actually
        # HOLDS an order back from the kitchen — is written in exactly one
        # place, inside mark_paid, which a pay-at-pickup order never reaches
        # before the counter. So the hold was never taken. The customer chose
        # 7:30pm, the kitchen got the order immediately, and the food then sat
        # until the 45-minute pickup TTL abandoned it.
        #
        # Taking the money is what the hold has always been anchored to, and
        # un-anchoring it is a real piece of work rather than a line here, so
        # the honest answer for now is no. Refused BEFORE any row is written,
        # with prose the app renders verbatim.
        # Direct UPI (035) is refused for the same reason and by the same
        # mechanism: release_at is written only in mark_paid, which it also
        # never reaches. Same error code, because the customer's remedy is
        # identical — order it for now — and a second code for the same
        # sentence would only be something else for the app to branch on.
        if non_gateway and getattr(payload, "requested_pickup_at", None) is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "SCHEDULING_UNAVAILABLE_FOR_PICKUP_PAYMENT",
                    "message": (
                        "Pay at pickup is available for orders collected as "
                        "soon as they are ready."
                        if pay_at_pickup else
                        "Paying by UPI is available for orders collected as "
                        "soon as they are ready."
                    ),
                },
            )

        # The global abuse cap, re-checked with this order excluded.
        #
        # _resolve_payment_method already consulted it to decide what to OFFER,
        # so reaching here with an open order means a race: two checkouts in
        # flight at once. Checked again for the same reason the stock cap is
        # checked inside the transaction — the offer is advisory, the write is
        # authoritative. Raised as its own error code so the app can deep-link
        # to the order it is talking about.
        # Shared by BOTH non-gateway methods, and the cap counts them TOGETHER
        # (see _open_pickup_order_id). One open unpaid order is the limit
        # whichever way it was going to be paid: the exposure being capped is a
        # person holding food they have not paid for, and it makes no
        # difference to the restaurant which of the two buttons they pressed.
        if non_gateway:
            open_id = await CarevoService._open_pickup_order_id(db, customer)
            if open_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "OPEN_PICKUP_ORDER_PENDING",
                        "order_id": open_id,
                        "message": (
                            "You already have an order waiting to be collected. "
                            "Pick that one up first."
                        ),
                    },
                )

        requested_pickup_at = CarevoService._normalise_requested_pickup(
            getattr(payload, "requested_pickup_at", None))

        avail = CarevoService.outlet_availability(
            gate.opens_at, gate.closes_at, bool(gate.is_manually_closed))
        if requested_pickup_at is None:
            # ASAP — unchanged. Anything short of fully open refuses, including
            # closing_soon, because the kitchen has no room for an order now.
            if avail["status"] != AVAIL_OPEN:
                raise HTTPException(status_code=409, detail=avail["reason"])
        elif avail["status"] == AVAIL_CLOSED:
            # SCHEDULED — survives closing_soon, which is the whole point:
            # "not enough room to cook this RIGHT NOW" is not an answer to a
            # request for 19:30, and the arrival gate below judges that time on
            # its own merits. A CLOSED shutter still refuses, though. It means
            # either the owner flipped the manual switch (a now-flag we cannot
            # meaningfully evaluate against a future instant, so the safe
            # reading is no) or nobody is there at all — and taking money for a
            # slot with no one present to see the order land is a different and
            # worse promise than making someone wait.
            raise HTTPException(status_code=409, detail=avail["reason"])

        # Universal arrival-feasibility gate (migration 031). Every mode, every
        # order — declared-arrival, GPS-estimated, and scheduled alike. Runs
        # before any row is written, for the same reason the hours gate does.
        await CarevoService._assert_arrival_feasible(
            db, gate=gate, outlet_id=payload.outlet_id,
            transport_mode=getattr(payload, "transport_mode", None),
            origin_lat=getattr(payload, "origin_lat", None),
            origin_lng=getattr(payload, "origin_lng", None),
            declared_arrival_at=getattr(payload, "declared_arrival_at", None),
            requested_pickup_at=requested_pickup_at)

        # SCHEDULED-RELEASE feasibility gate (launch blocker). A no-op for
        # instant orders — only runs when requested_pickup_at is set — and
        # separate from the arrival gate above: that gate asks "can the
        # CUSTOMER get here in time", this one asks "can the KITCHEN have it
        # ready", and a slot can fail either one independently.
        await CarevoService._assert_scheduled_release_feasible(
            db, outlet_id=payload.outlet_id, items=payload.items,
            requested_pickup_at=requested_pickup_at)

        # STOCK (033): reclaim lapsed holds BEFORE anything reads availability.
        #
        # Position matters and is the whole reason this is here rather than next
        # to reserve_for_order below. reserve_for_order flips is_available to
        # false when an item hits zero, so somebody's abandoned cart leaves the
        # dish reading "unavailable" — and the snapshot query immediately below
        # reads is_available and refuses the order on it. Sweeping after that
        # gate would reclaim the units a moment too late to be allowed to use
        # them, and the customer would be told the dish is off the menu while
        # its stock sat in a lapsed hold.
        #
        # commit=False is required, not cosmetic: this is mid-transaction and an
        # internal commit would persist a partially built order. It also makes
        # the release atomic with the reservation taken further down, so units
        # this frees cannot be taken by anyone else in the gap.
        from app.modules.carevo_customer.stock import StockService
        await StockService.sweep_expired(db, outlet_id=payload.outlet_id,
                                         commit=False)

        # Snapshot name + price from menu_items.
        item_ids = [str(i.menu_item_id) for i in payload.items]
        rows = (await db.execute(text("""
            SELECT id, name, base_price, is_available, is_active
            FROM menu_items WHERE id = ANY(:ids)
        """), {"ids": item_ids})).fetchall()
        by_id = {str(r.id): r for r in rows}

        order = CustomerOrder(
            customer_id=customer.id,
            outlet_id=payload.outlet_id,
            status="CREATED",
            payment_status="PENDING",
            customer_notes=payload.customer_notes,
            total_amount=0,
        )
        db.add(order)
        await db.flush()  # assign order.id

        # PAYMENT MODE + CONTACT SNAPSHOT (migration 034), in the SAME
        # transaction as the order insert.
        #
        # Raw SQL because none of these columns is ORM-mapped — the same
        # treatment the 031 columns get immediately below, and for the same
        # reason (see the migration header).
        #
        # The contact is a SNAPSHOT of the account's verified phone and name.
        # Nothing here reads the request body: a client-supplied phone is never
        # accepted, because the restaurant is about to cook on the strength of
        # that number. For a PREPAID order both stay NULL, which is what keeps
        # the owner queue name-free everywhere it is name-free today.
        #
        # call_state starts at PENDING: the order exists, and nobody has rung
        # yet. That is the state the owner app's Call button acts on.
        await db.execute(text("""
            UPDATE customer_orders
               SET payment_mode = :mode,
                   contact_name = :cname,
                   contact_phone = :cphone,
                   call_state = :cstate
             WHERE id = :id
        """), {
            "mode": payment_mode,
            # Snapshotted for BOTH non-gateway modes (035). A direct-UPI order
            # needs it too: if the money does not arrive, or arrives short, the
            # restaurant has to be able to reach the person who claimed to have
            # sent it.
            "cname": (customer.name or None) if non_gateway else None,
            "cphone": (customer.phone_number or None) if non_gateway else None,
            # call_state is PAY-AT-PICKUP ONLY. Nobody rings a direct-UPI
            # customer as part of the flow — the restaurant checks its own UPI
            # app — so leaving it NULL is what keeps "is there a call to make"
            # answerable from this column alone.
            "cstate": "PENDING" if pay_at_pickup else None,
            "id": str(order.id),
        })

        # PE Step 3 (FR-C1/C2): persist travel context on the order.
        if any(v is not None for v in (payload.transport_mode, payload.origin_lat,
                                       payload.origin_lng, payload.origin_source,
                                       getattr(payload, "declared_arrival_at", None),
                                       requested_pickup_at)):
            await db.execute(text("""
                UPDATE customer_orders SET transport_mode=:tm, origin_lat=:la,
                       origin_lng=:ln, origin_source=:os,
                       declared_arrival_at=:dec, requested_pickup_at=:req
                WHERE id=:id
            """), {"tm": payload.transport_mode, "la": payload.origin_lat,
                   "ln": payload.origin_lng, "os": payload.origin_source,
                   # Train only. Stored for any mode that sends it, but nothing
                   # reads it outside the train branch, so a stray value is inert.
                   "dec": getattr(payload, "declared_arrival_at", None),
                   # Scheduled pickup (031). Stored on the CREATED order, but
                   # release_at stays NULL until payment: an unpaid order is not
                   # held, it simply does not exist as far as the kitchen is
                   # concerned, and the hold only has meaning once money moved.
                   "req": requested_pickup_at,
                   "id": str(order.id)})

        total = 0.0
        for line in payload.items:
            mi = by_id.get(str(line.menu_item_id))
            if not mi:
                raise HTTPException(status_code=400, detail=f"Unknown menu item {line.menu_item_id}")
            if not (mi.is_available and mi.is_active):
                raise HTTPException(status_code=409, detail=f"Item unavailable: {mi.name}")
            price = float(mi.base_price) if mi.base_price is not None else 0.0
            total += price * line.quantity
            db.add(CustomerOrderItem(
                customer_order_id=order.id,
                menu_item_id=line.menu_item_id,
                name_snap=mi.name,
                price_snap=price,
                quantity=line.quantity,
                customizations=line.customizations,
                item_notes=line.item_notes,
            ))

        # STOCK RESERVATION (migration 033), in THIS transaction, before any
        # payment exists. Untracked items (stock_remaining IS NULL) are skipped
        # entirely, so this is a no-op for every item until a restaurant sets a
        # number.
        #
        # Reserving here rather than at payment is deliberate: the alternative
        # lets a customer complete checkout for a dish that sold out while they
        # were typing, and they have then been CHARGED for food that does not
        # exist. A 409 before payment is recoverable; a refund is not.
        #
        # Raises 409 ITEM_SOLD_OUT with the real remaining count. Because it is
        # the same transaction, a refusal rolls the whole order back — there is
        # no state where an order exists with a partial hold.
        # HOARDING CAP: one live UNPAID hold per customer per outlet.
        #
        # Without it, the TTL is a loophole rather than a limit. Nothing stops
        # one account placing orders in a loop and abandoning each, and because
        # each attempt takes a fresh 600-second hold, a handful of requests can
        # hold a dish's entire stock for ten minutes at a time, indefinitely,
        # at zero cost — no payment is ever required to do it.
        #
        # Deliberately NOT a rate limit. The resource being protected is the
        # restaurant's stock, not the endpoint, so the cap is "how many of your
        # holds may exist at once" rather than "how often you may ask".
        #
        # Runs AFTER the sweep so a lapsed hold can never block its own owner,
        # and before reserve_for_order so no units are taken on a request that
        # is about to be refused.
        #
        # PAID orders are untouched: payment_status is excluded below, so a
        # customer with food on the way can order again immediately. Terminal
        # orders are excluded too — a cancel releases its hold, so this is
        # belt-and-braces against a hold that outlived its order.
        existing_hold = (await db.execute(text("""
            SELECT co.id
              FROM stock_reservations sr
              JOIN customer_orders co ON co.id = sr.order_id
             WHERE sr.state = 'HELD'
               AND sr.expires_at > now()
               AND sr.order_id <> :self_id
               AND co.customer_id = :cid
               AND co.outlet_id = :oid
               AND co.payment_status <> 'PAID'
               AND upper(coalesce(co.status, '')) <> ALL(:terminal)
             LIMIT 1
        """), {"self_id": str(order.id), "cid": str(customer.id),
               "oid": str(payload.outlet_id),
               "terminal": list(_TERMINAL_STATUSES)})).first()
        if existing_hold is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "UNPAID_ORDER_PENDING",
                    # DATA, for the app to deep-link the customer to the order
                    # it is talking about. customer_orders has no readable_id
                    # (that column is on the legacy `orders` table) and
                    # pickup_code is NULL until payment, so the uuid is the only
                    # identifier an unpaid order has — which is exactly why it
                    # stays out of the prose below.
                    "order_id": str(existing_hold[0]),
                    # Phrased as the action the customer can take. "One order at
                    # a time" alone reads as a refusal with no way out.
                    "message": (
                        "You already have an unpaid order at this restaurant. "
                        "Finish paying for it, or cancel it, before placing "
                        "another."
                    ),
                },
            )

        await StockService.reserve_for_order(db, order.id, payload.items)

        gross = round(total, 2)

        # Coupon (migration 010). Applied BEFORE the gateway order is created so
        # the customer is only ever charged the discounted amount — settling the
        # full amount and refunding the difference would be a second money path
        # to get wrong.
        discount = 0.0
        promotion_label: Optional[str] = None
        wants_coupon = bool(getattr(payload, "coupon_code", None))
        wants_promotion = bool(
            getattr(payload, "promotion_id", None)
            or getattr(payload, "promotion_code", None)
        )

        # No stacking in V1. Rejected outright rather than quietly honouring one
        # of the two: a customer who supplies both and is charged for one has no
        # way to tell which was ignored. The DB backs this up as well —
        # idx_promo_redemption_one_per_order allows a single promotion per order.
        if wants_coupon and wants_promotion:
            raise HTTPException(
                status_code=422,
                detail="Use either a coupon or an offer on an order, not both.",
            )

        if wants_coupon:
            discount = await CarevoService._consume_points_coupon(
                db, customer, order_id=order.id, gross=gross,
                code=payload.coupon_code,
            )
        elif wants_promotion:
            # Promotions (migration 016). Runs in this same open transaction, so
            # a failure below rolls the redemption back and the offer stays
            # claimable — identical discipline to _consume_points_coupon.
            applied = await PromotionService.apply_to_order(
                db,
                customer_id=customer.id,
                outlet_id=payload.outlet_id,
                order_id=order.id,
                gross=gross,
                promotion_id=getattr(payload, "promotion_id", None),
                code=getattr(payload, "promotion_code", None),
            )
            discount = applied["discount_amount"]
            promotion_label = applied["label"]

        order.discount_amount = discount
        # Never below zero: a ₹100 coupon on an ₹80 order settles at ₹0, and the
        # unused ₹20 is not carried anywhere (single-use means single-use).
        order.total_amount = round(max(gross - discount, 0.0), 2)

        # ---------------- PAY AT PICKUP: no gateway at all (034) ------------
        #
        # Returns BEFORE `gw = get_gateway()` below, so no gateway order is
        # created, no payment session is minted and no PaymentTransaction row
        # exists. There is nothing to charge yet — the money arrives at the
        # counter, and the transaction row is written then by
        # record_pickup_payment.
        #
        # Cashfree is untouched by this branch, in both senses: the block below
        # is unchanged, and a PREPAID order at this same outlet still runs
        # through it exactly as before.
        if pay_at_pickup:
            # The acceptance clock starts HERE, not at payment — there is no
            # payment to start it. begin_awaiting runs in this transaction and
            # does not commit (by contract), so the AWAITING state, the
            # deadline and the durable schedule row all land atomically with
            # the order itself. An order that exists but is not yet on anyone's
            # clock is not a state that can be observed.
            from app.modules.carevo_customer.acceptance import AcceptanceService
            await AcceptanceService.begin_awaiting(
                db, order, reason="pay_at_pickup_placed")

            await CarevoService._write_order_created_event(
                db, order, customer, payload, requested_pickup_at,
                payment_mode=payment_mode)
            await db.commit()

            # Rung 1 of the alert ladder, AFTER the commit and best-effort —
            # same contract as the payment path. A push failure must not undo
            # an order that is already placed; the sweeper re-pushes from
            # alert_count regardless.
            await AcceptanceService.send_first_alert(db, order)

            return {
                "id": order.id,
                "status": "CREATED",
                "total_amount": order.total_amount,
                # No payment block: there is no gateway session to open. The
                # field is Optional precisely so this can be absent rather than
                # faked — see CreateOrderOut.
                "payment": None,
                "payment_mode": payment_mode,
                "amount_due_at_pickup": order.total_amount,
                "original_amount": gross,
                "discount_amount": discount,
                "final_amount": order.total_amount,
                "promotion_label": promotion_label,
            }

        # ---------------- DIRECT UPI: no gateway either (035) ---------------
        #
        # Shares the no-gateway property with pay-at-pickup but NOT the clock.
        # The acceptance window does not open here, because there is nothing
        # for the restaurant to decide yet: it cannot confirm a payment the
        # customer has not told it about, and alerting staff to an order whose
        # money has not been claimed would be asking them to stare at their
        # UPI app on spec. begin_awaiting fires on the CLAIM instead
        # (claim_upi_payment), which is the first moment there is a question to
        # answer.
        #
        # So the only clock running now is the stock hold, and the pay window
        # is sized to sit inside it — see UPI_PAY_WINDOW_SECONDS.
        if upi_manual:
            vpa_row = (await db.execute(text(
                "SELECT upi_vpa, upi_payee_name FROM outlets WHERE id = :oid"),
                {"oid": str(payload.outlet_id)})).first()

            await CarevoService._write_order_created_event(
                db, order, customer, payload, requested_pickup_at,
                payment_mode=payment_mode)
            await db.commit()

            return {
                "id": order.id,
                "status": "CREATED",
                "total_amount": order.total_amount,
                "payment": None,
                "payment_mode": payment_mode,
                "amount_due_at_pickup": 0,
                # Everything the app needs to build a upi:// intent, computed
                # here rather than in the client: the VPA and payee are the
                # restaurant's and the app has no other way to know them, and
                # `note` has to match what the restaurant will see in its own
                # UPI app next to the amount.
                "upi_payment": CarevoService._upi_payment_block(
                    order, vpa_row[0] if vpa_row else None,
                    vpa_row[1] if vpa_row else None),
                "original_amount": gross,
                "discount_amount": discount,
                "final_amount": order.total_amount,
                "promotion_label": promotion_label,
            }

        # Create gateway order (stub / razorpay-shaped)
        gw = get_gateway()
        # Awaited now that the interface is async — a real gateway is a network
        # call, and running it synchronously would block the event loop.
        # `receipt` carries OUR order id, which Cashfree echoes back on the
        # webhook so no correlation table is needed.
        #
        # EVERY way this call can fail used to become a naked 500.
        # CashfreeGateway raised a bare RuntimeError for all three of its
        # refusals (credentials absent, a >=400 from Cashfree, a response with
        # no payment_session_id); httpx raised its own errors for DNS, TLS and
        # timeouts; and res.json() raised ValueError when an error page came
        # back under a 200. Unhandled, every one of them reached the customer
        # as "Request failed (500)." on the payment page (api_client.dart:392)
        # — no cause, nothing to act on, and indistinguishable from a crash in
        # our own code.
        #
        # NONE of them is an internal error, and they do not deserve the same
        # answer either, which is why the gateway now raises three distinct
        # types and this maps them three ways:
        #
        #   GatewayConfigError  -> 503. Our deployment is missing credentials.
        #       Retrying cannot help until an operator acts, but the customer's
        #       order is fine and will work once it is fixed. This is the
        #       likeliest thing to be wrong on a fresh deploy: render.yaml sets
        #       PAYMENT_GATEWAY=cashfree as a literal value while
        #       CASHFREE_APP_ID and CASHFREE_SECRET_KEY are `sync: false`, so
        #       the blueprint selects the live gateway but cannot supply its
        #       secrets.
        #
        #   GatewayRequestError -> 422. The ORDER cannot be charged as it
        #       stands (today: a discount that takes it to ₹0, which is below
        #       Cashfree's ₹1 floor). Nothing is down; telling the customer
        #       "payments are unavailable" would be a lie and they would retry
        #       forever. The gateway supplies the prose because only it knows
        #       which constraint was missed.
        #
        #   anything else       -> 502. The provider refused, timed out or
        #       answered with something unusable. A genuine upstream failure.
        #
        # The catch-all is deliberately broad (RuntimeError covers the whole
        # GatewayError family and any gateway still raising bare ones; httpx
        # and ValueError cover an implementation that does not wrap). A 500 out
        # of this call is never the right answer, so the net is wider than the
        # list of things known to be thrown today.
        #
        # 502/503 are both honestly retryable here: the order row and the stock
        # hold above are still UNCOMMITTED, so the session closes without a
        # commit and nothing survives to collide with the retry (proven in
        # test_api_payment_gateway_failure.py).
        #
        # Logged server-side with the order id and the provider's own response
        # body, which is where diagnosis belongs and is the one place the
        # offending field is actually named. Credentials are not in the log:
        # they travel in request headers and `body` is Cashfree's response. The
        # customer-facing message names neither the provider nor our config
        # state, because the app renders `detail["message"]` verbatim.
        try:
            g_order = await gw.create_order(
                order.total_amount, currency="INR", receipt=str(order.id),
                customer={
                    "id": str(customer.id),
                    "phone": customer.phone_number,
                    "email": customer.email,
                    "name": customer.name,
                },
            )
        except GatewayConfigError as exc:
            logger.error(
                "payment gateway %s is NOT CONFIGURED; refused order %s "
                "(outlet=%s, amount=%s): %s",
                getattr(gw, "name", type(gw).__name__), order.id,
                payload.outlet_id, order.total_amount, exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "PAYMENT_GATEWAY_UNCONFIGURED",
                    "message": (
                        "Payments are temporarily unavailable. You have not "
                        "been charged — please try again in a moment."
                    ),
                },
                headers={"Retry-After": "30"},
            ) from exc
        except GatewayRequestError as exc:
            logger.warning(
                "payment gateway %s cannot charge order %s "
                "(outlet=%s, amount=%s): %s",
                getattr(gw, "name", type(gw).__name__), order.id,
                payload.outlet_id, order.total_amount, exc)
            raise HTTPException(
                status_code=422,
                detail={"error": exc.code, "message": exc.customer_message},
            ) from exc
        except (RuntimeError, httpx.HTTPError, ValueError) as exc:
            logger.error(
                "payment gateway %s failed on order %s (outlet=%s, amount=%s): "
                "%s [upstream_status=%s upstream_body=%r]",
                getattr(gw, "name", type(gw).__name__), order.id,
                payload.outlet_id, order.total_amount, exc,
                getattr(exc, "status_code", None), getattr(exc, "body", None),
                exc_info=True)
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "PAYMENT_GATEWAY_ERROR",
                    "message": (
                        "We could not reach the payment provider. You have not "
                        "been charged — please try again in a moment."
                    ),
                },
                headers={"Retry-After": "30"},
            ) from exc

        db.add(PaymentTransaction(
            customer_order_id=order.id,
            gateway=g_order.gateway,
            gateway_order_id=g_order.gateway_order_id,
            amount=order.total_amount,
            currency=g_order.currency,
            status="CREATED",
            method=None,
        ))
        self_session_id = g_order.payment_session_id

        # FR-E1: ORDER_CREATED in the SAME transaction as the order insert.
        # Shared with the pay-at-pickup path above — one definition of the
        # payload, so the two cannot drift.
        await CarevoService._write_order_created_event(
            db, order, customer, payload, requested_pickup_at,
            payment_mode=payment_mode)
        await db.commit()

        return {
            "id": order.id,
            "status": "CREATED",
            "total_amount": order.total_amount,
            "payment": {
                "gateway": g_order.gateway,
                "gateway_order_id": g_order.gateway_order_id,
                "amount": g_order.amount,
                "currency": g_order.currency,
                "key_id": g_order.key_id,
                # What the Cashfree Flutter SDK opens checkout with. Null for
                # the Razorpay-shaped stub, which opens on order_id + key_id.
                "payment_session_id": self_session_id,
            },
            # Additive (034). PREPAID here by construction — the pay-at-pickup
            # path returned long before this point. Echoed anyway so the app
            # reads one field on both paths instead of inferring the mode from
            # whether `payment` happens to be null.
            "payment_mode": payment_mode,
            "amount_due_at_pickup": 0,
            # The struck-through-price breakdown, computed here rather than in
            # the app: `gross` is the pre-discount figure and only this function
            # has ever known it.
            "original_amount": gross,
            "discount_amount": discount,
            "final_amount": order.total_amount,
            "promotion_label": promotion_label,
        }

    @staticmethod
    def short_order_number(order_id) -> str:
        """The last 6 hex characters of the order id, upper-cased.

        What goes in the UPI note, so the restaurant can match the payment in
        its own app against the order on its tablet. `customer_orders` has no
        readable_id — that column is on the legacy `orders` table — so this is
        derived rather than stored.

        It is NOT a secret and NOT a pickup code: it travels through the
        customer's UPI app and appears on both parties' bank statements, which
        is exactly why the pickup code must never be used here. Collisions are
        possible in principle (16^6 across all orders ever) but it is only ever
        read by one restaurant against its own small set of open orders, next
        to an amount.
        """
        return str(order_id).replace("-", "")[-6:].upper()

    @staticmethod
    async def upi_payment_for_order(db: AsyncSession, order) -> Optional[dict]:
        """The UPI intent block for an existing order, by outlet lookup.

        Used by GET /customer/orders/{id} so the pay screen survives the app
        being killed: the block is rebuilt from the outlet's CURRENT VPA rather
        than stored on the order. That is deliberate — if the restaurant
        corrects a typo in its UPI ID, an order still waiting to be paid should
        send money to the corrected one, not to the string that was live when
        the order was placed.
        """
        row = (await db.execute(text(
            "SELECT upi_vpa, upi_payee_name FROM outlets WHERE id = :oid"),
            {"oid": str(order.outlet_id)})).first()
        if row is None:
            return None
        return CarevoService._upi_payment_block(order, row[0], row[1])

    @staticmethod
    def _upi_payment_block(order, vpa: Optional[str],
                           payee: Optional[str]) -> Optional[dict]:
        """What the app needs to build a `upi://pay?...` intent.

        None when the outlet has no VPA, which
        ck_outlets_upi_manual_requires_vpa makes impossible for an outlet that
        has the method enabled — so this is defensive rather than a real state.
        Returning None instead of a half-filled block means a client cannot
        build an intent that would send money nowhere.

        `amount` is a float of the order total; the app formats it to two
        decimals for the `am=` parameter. The server does not pre-format it,
        because a currency string is a presentation choice and this payload is
        also read by the owner app.
        """
        if not vpa:
            return None
        return {
            "vpa": vpa,
            "payee_name": payee or "",
            "amount": float(order.total_amount or 0),
            "note": CarevoService.short_order_number(order.id),
        }

    @staticmethod
    async def _write_order_created_event(
        db: AsyncSession, order, customer: Customer, payload,
        requested_pickup_at, *, payment_mode: str,
    ) -> None:
        """FR-E1: ORDER_CREATED, in the caller's transaction. No commit.

        Extracted so the prepaid and pay-at-pickup paths share ONE definition
        of the payload. They diverge on whether a gateway order exists, which
        is not something this event has ever recorded, so there was never a
        reason for two copies of it to drift apart.
        """
        await pe.write_event(
            db, order.id, pe.ORDER_CREATED,
            actor_type="customer", actor_id=customer.id, source="tap",
            outlet_id=order.outlet_id,
            payload={
                "items": [
                    {"menu_item_id": str(i.menu_item_id), "quantity": i.quantity}
                    for i in payload.items
                ],
                # origin/transport are populated once Step 3 (customer_app) lands.
                "transport_mode": getattr(payload, "transport_mode", None),
                "origin_lat": getattr(payload, "origin_lat", None),
                "origin_lng": getattr(payload, "origin_lng", None),
                "origin_source": getattr(payload, "origin_source", None),
                # Scheduled pickup (031), in the append-only log as well as on
                # the row: order_events is what the timeline view reads, and a
                # scheduled order whose timeline never mentions the schedule
                # would be unexplainable after the fact.
                "requested_pickup_at": (
                    requested_pickup_at.isoformat() if requested_pickup_at else None),
                # Which money path this order took (034). In the log as well as
                # on the row because the event stream is what the timeline view
                # reads, and "why did this order never have a payment session"
                # must be answerable from it alone.
                "payment_mode": payment_mode,
            },
        )

    @staticmethod
    async def get_order(db: AsyncSession, order_id: uuid.UUID, customer: Customer) -> CustomerOrder:
        """One of the customer's own orders, by id.

        Honours `customers.history_cutoff_at` (migration 022) exactly as
        list_my_orders does. Without it the cutoff hid an order from the LIST
        while a direct link still returned it in full — a hole the shape of the
        cross-outlet verify-pickup one fixed earlier: the filter existed, but
        only on the path someone happened to look at.

        The refusal is a 404, deliberately identical to "no such order", rather
        than a 403 that would confirm the id exists. Nothing is deleted; the row
        is still there and clearing the cutoff restores access instantly.
        """
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(order.customer_id) != str(customer.id):
            raise HTTPException(status_code=403, detail="Not your order")
        cutoff = getattr(customer, "history_cutoff_at", None)
        if cutoff is not None and order.created_at is not None and order.created_at < cutoff:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @staticmethod
    async def shadow_estimate(db: AsyncSession, order_id) -> Optional[dict]:
        """§16 wide range for the customer. Compute-on-read if the twin is stale
        and the order is still live (§17). Best-effort — never raises to the caller."""
        live = (await db.execute(text(
            "SELECT status FROM customer_orders WHERE id = :o"), {"o": str(order_id)})).scalar()
        twin = (await db.execute(text(
            "SELECT inputs, stale_after FROM order_twin WHERE order_id = :o"
        ), {"o": str(order_id)})).first()
        stale = twin is None or (twin.stale_after and twin.stale_after < datetime.now(timezone.utc))
        if live in _LIVE_STATUSES and stale:
            try:
                from app.modules.prediction.service import PredictionService
                res = await PredictionService.recompute_twin(db, order_id)
                if res:
                    lo, hi = res["shadow_range_min"]
                    return {"low_min": lo, "high_min": hi, "approximate": res.get("degraded", True)}
            except Exception:
                await db.rollback()
        if twin and twin.inputs:
            inp = twin.inputs if isinstance(twin.inputs, dict) else json.loads(twin.inputs)
            sr = inp.get("shadow_range_min")
            if sr:
                return {"low_min": sr[0], "high_min": sr[1],
                        "approximate": inp.get("travel_source") == "haversine_fallback"}
        return None

    # -------------------- PE Step 3: customer events -----------------------
    @staticmethod
    async def _owned_order_row(db: AsyncSession, order_id, customer):
        row = (await db.execute(text(
            "SELECT id, outlet_id, customer_id FROM customer_orders WHERE id = :o"
        ), {"o": str(order_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(row.customer_id) != str(customer.id):
            raise HTTPException(status_code=403, detail="Not your order")
        return row

    @staticmethod
    async def _has_event(db: AsyncSession, order_id, event_type) -> bool:
        return (await db.execute(text(
            "SELECT 1 FROM order_events WHERE order_id = :o AND event_type = :t LIMIT 1"
        ), {"o": str(order_id), "t": event_type})).first() is not None

    @staticmethod
    async def record_departed(db, order_id, customer, lat, lng) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        # FR-C3: whichever fires first (tap or inferred) wins — idempotent.
        if await CarevoService._has_event(db, order_id, pe.CUSTOMER_DEPARTED):
            return {"ok": True, "recorded": False, "detail": "already departed"}
        await pe.write_event(
            db, order_id, pe.CUSTOMER_DEPARTED, actor_type="customer",
            actor_id=customer.id, source="tap", outlet_id=row.outlet_id,
            payload={"lat": lat, "lng": lng})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_location_ping(db, order_id, customer, lat, lng, accuracy_m, speed_mps) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        last = (await db.execute(text(
            "SELECT occurred_at, payload FROM order_events WHERE order_id = :o "
            "AND event_type = 'LOCATION_PING' ORDER BY seq DESC LIMIT 1"
        ), {"o": str(order_id)})).first()
        if last is not None:
            lp = last.payload if isinstance(last.payload, dict) else json.loads(last.payload)
            dt_s = (datetime.now(timezone.utc) - last.occurred_at).total_seconds()
            dist_m = float("inf")
            if lp.get("lat") is not None and lp.get("lng") is not None:
                dist_m = CarevoService._haversine_km(
                    float(lp["lat"]), float(lp["lng"]), float(lat), float(lng)) * 1000.0
            # FR-E5 / NFR-7: reject unless ≥ 90s OR ≥ 300m since the last ping.
            if dt_s < 90 and dist_m < 300:
                return {"ok": True, "recorded": False, "detail": "throttled"}
        await pe.write_event(
            db, order_id, pe.LOCATION_PING, actor_type="customer",
            actor_id=customer.id, source="system", outlet_id=row.outlet_id,
            payload={"lat": lat, "lng": lng, "accuracy_m": accuracy_m, "speed_mps": speed_mps})
        # FR-C4: 150m geofence is inferred server-side so the client stays a dumb
        # location streamer. Emit CUSTOMER_ARRIVED once, when the ping lands inside
        # the ring around the outlet (idempotent — a prior tap/geofence wins).
        arrived = False
        oc = (await db.execute(text(
            "SELECT latitude, longitude FROM outlets WHERE id = :o"
        ), {"o": str(row.outlet_id)})).first()
        if oc and oc.latitude is not None and oc.longitude is not None:
            dist_m = CarevoService._haversine_km(
                float(lat), float(lng), float(oc.latitude), float(oc.longitude)) * 1000.0
            if dist_m <= 150.0 and not await CarevoService._has_event(
                    db, order_id, pe.CUSTOMER_ARRIVED):
                await pe.write_event(
                    db, order_id, pe.CUSTOMER_ARRIVED, actor_type="customer",
                    actor_id=customer.id, source="geofence", outlet_id=row.outlet_id,
                    payload={"accuracy_m": accuracy_m, "distance_m": round(dist_m, 1)})
                arrived = True
        await db.commit()
        return {"ok": True, "recorded": True, "detail": "arrived" if arrived else None}

    @staticmethod
    async def record_arrived(db, order_id, customer, accuracy_m, source) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        if await CarevoService._has_event(db, order_id, pe.CUSTOMER_ARRIVED):
            return {"ok": True, "recorded": False, "detail": "already arrived"}
        await pe.write_event(
            db, order_id, pe.CUSTOMER_ARRIVED, actor_type="customer",
            actor_id=customer.id, source=("geofence" if source == "geofence" else "tap"),
            outlet_id=row.outlet_id, payload={"accuracy_m": accuracy_m})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_wait_feedback(db, order_id, customer, bucket) -> dict:
        row = await CarevoService._owned_order_row(db, order_id, customer)
        if await CarevoService._has_event(db, order_id, pe.WAIT_FEEDBACK):
            return {"ok": True, "recorded": False, "detail": "already submitted"}
        await pe.write_event(
            db, order_id, pe.WAIT_FEEDBACK, actor_type="customer",
            actor_id=customer.id, source="tap", outlet_id=row.outlet_id,
            payload={"bucket": bucket})
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def record_picked_up(db, order_id, customer) -> dict:
        """The customer's own "I've picked this up" ack (migration 023).

        Mirrors record_departed / record_arrived exactly: owned-order check,
        idempotent via _has_event, one append-only CUSTOMER_PICKED_UP event,
        commit. Deliberately does NOT move order.status — staff verifying the
        pickup code (PICKUP_VERIFIED → COMPLETED) remains the only real
        completion, unchanged by this. This event only gives the customer's
        acknowledgment a durable server record instead of an on-device flag.
        """
        row = await CarevoService._owned_order_row(db, order_id, customer)
        if await CarevoService._has_event(db, order_id, pe.CUSTOMER_PICKED_UP):
            return {"ok": True, "recorded": False, "detail": "already acknowledged"}
        await pe.write_event(
            db, order_id, pe.CUSTOMER_PICKED_UP, actor_type="customer",
            actor_id=customer.id, source="tap", outlet_id=row.outlet_id)
        await db.commit()
        return {"ok": True, "recorded": True}

    @staticmethod
    async def pickup_progress(db, order_id) -> dict:
        """Which of the customer's own pickup-journey acknowledgments have been
        recorded for this order: departed / arrived / picked_up.

        One round trip rather than three: reads all three CUSTOMER_* event types
        in a single query. Used by GET /customer/orders/{id} (OrderOut) so the
        app can be server-sourced instead of trusting only local persistence.
        Reads order_events, the same append-only log record_departed /
        record_arrived / record_picked_up write to.
        """
        rows = (await db.execute(text("""
            SELECT DISTINCT event_type FROM order_events
             WHERE order_id = :o
               AND event_type IN
                   ('CUSTOMER_DEPARTED', 'CUSTOMER_ARRIVED', 'CUSTOMER_PICKED_UP')
        """), {"o": str(order_id)})).scalars().all()
        seen = set(rows)
        return {
            "departed": pe.CUSTOMER_DEPARTED in seen,
            "arrived": pe.CUSTOMER_ARRIVED in seen,
            "picked_up": pe.CUSTOMER_PICKED_UP in seen,
        }

    # ---------------------------- Payment ----------------------------------
    @staticmethod
    async def _expire_stale_pickups(
        db: AsyncSession, *, outlet_id=None, order_id=None
    ) -> int:
        """Check-on-read expiry: any live/waiting order untouched for longer than
        PICKUP_TTL_MINUTES auto-transitions to ABANDONED, freeing its pickup_code.
        Done in SQL (now()/interval vs the timestamptz column) to avoid naive-vs-
        aware datetime bugs. Commits its own maintenance UPDATE. Returns rowcount.
        Scope to one outlet or one order; at least one must be given.

        HELD ORDERS ARE EXEMPT (migration 031) — `release_at IS NULL`.

        Note this is NOT the same clause the owner queue uses. The queue asks a
        TIME question ("may the restaurant see it yet") and can afford to be
        eager: (release_at IS NULL OR release_at <= now()). This asks a STATE
        question ("is this order's pickup window running yet"), and the time
        form would be a live bug: between release_at passing and the release
        actually executing, an order would be TTL-eligible while still carrying
        the updated_at stamped at PAYMENT, hours earlier — so the very next
        sweep would ABANDON a paid order at the exact moment it was due to
        reach the kitchen. The sweeper also runs FIRST in list_active_orders,
        which is precisely where that race would be lost.

        Clearing release_at at release, in the same transaction that hands the
        order to advance_status (which stamps updated_at=now()), is therefore
        what restarts the 45-minute pickup window at the RELEASE moment rather
        than at payment. An unscheduled order has release_at NULL and this
        predicate is byte-for-byte what it always was.
        """
        clauses = [
            "status = ANY(:live)",
            "release_at IS NULL",
            "updated_at < now() - make_interval(mins => :ttl)",
        ]
        params = {
            "live": list(_LIVE_STATUSES),
            "ttl": settings.PICKUP_TTL_MINUTES,
        }
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)
        if order_id is not None:
            clauses.append("id = :iid")
            params["iid"] = str(order_id)
        # refund_required is set HERE, in the same UPDATE, for any order that
        # had actually been paid (migration 032).
        #
        # This is the discrepancy the flag was added to make visible. The
        # comment beside ORDER_ABANDONED describes this sweeper as expiring
        # "an order nobody paid for" — but _LIVE_STATUSES is
        # {PAID, RECEIVED, PREPARING, READY}, so the predicate above has always
        # abandoned PAID orders too. A customer whose paid food was never
        # collected within the TTL is owed their money whether or not the copy
        # said so, and before this there was no queryable record of it.
        #
        # Conditional in SQL rather than in a second pass, so the flag can
        # never disagree with the status transition that caused it.
        rows = (await db.execute(text(
            # AND payment_mode = 'PREPAID' on all three, for the same reason as
            # reject_order: only a GATEWAY payment can enter the gateway refund
            # queue. An accepted direct-UPI order and a collected
            # pay-at-pickup order are both PAID, so the bare payment_status
            # test put money CareVo never received — and cannot reverse — into
            # /admin/orders/refund-due.
            #
            # A direct-UPI order that reaches the TTL has been paid to the
            # RESTAURANT and never collected. Nothing is flagged on either
            # axis: refund_required would be a lie about who holds the money,
            # and manual_refund_due would oblige a refund for food that was
            # made and waiting. It is the customer's own loss, which is the
            # same answer a collected-but-uncollected pay-at-pickup order gets.
            "UPDATE customer_orders SET status='ABANDONED', updated_at=now(), "
            "    refund_required = CASE WHEN payment_status = 'PAID' "
            "                           AND payment_mode = 'PREPAID' "
            "                           THEN true ELSE refund_required END, "
            "    refund_reason = CASE WHEN payment_status = 'PAID' "
            "                         AND payment_mode = 'PREPAID' "
            "                         AND NOT refund_required "
            "                         THEN 'ttl_abandoned' ELSE refund_reason END, "
            "    refund_flagged_at = CASE WHEN payment_status = 'PAID' "
            "                             AND payment_mode = 'PREPAID' "
            "                             AND NOT refund_required "
            "                             THEN now() ELSE refund_flagged_at END "
            "WHERE " + " AND ".join(clauses)
            + " RETURNING id, outlet_id, payment_status, payment_mode, customer_id"
        ), params)).fetchall()
        if rows:
            # A TTL-ABANDONED PAY-AT-PICKUP ORDER IS A NO-SHOW (migration 034).
            #
            # It is the same real-world event as the staff /no-show button —
            # food made, customer never came — arriving by clock instead of by
            # tap. It therefore has to carry the same consequence, or whether a
            # customer accrues a strike depends on which of the two got there
            # first, and a customer could avoid every strike simply by not
            # being noticed for 45 minutes.
            #
            # Stock is NOT returned on either path: release_for_order below is
            # HELD-only, and an accepted pay-at-pickup order's units are
            # COMMITTED. See mark_no_show for the full argument.
            #
            # PAY-AT-PICKUP ONLY, deliberately not both non-gateway modes. A
            # direct-UPI order that reaches the TTL has already been PAID (the
            # accept recorded it), so a customer who never collects it has lost
            # their own money rather than cost the restaurant food — the strike
            # would be punishing someone who already paid. An UNCLAIMED UPI
            # order never reaches _LIVE_STATUSES at all; it is cancelled by the
            # pay-window sweep instead.
            no_shows = [r for r in rows
                        if (r.payment_mode or "") == PAY_AT_PICKUP]
            for r in no_shows:
                await db.execute(text(
                    "UPDATE customers SET no_show_count = no_show_count + 1 "
                    "WHERE id = :cid"), {"cid": str(r.customer_id)})
                await pe.write_event(
                    db, r.id, pe.ORDER_NO_SHOW,
                    actor_type="system", source="system", outlet_id=r.outlet_id,
                    payload={"reason": "pickup_ttl_expired",
                             "ttl_minutes": settings.PICKUP_TTL_MINUTES,
                             "refund_required": False},
                )
            # FR-E1: one ORDER_ABANDONED per expired order, same transaction.
            for r in rows:
                await pe.write_event(
                    db, r.id, pe.ORDER_ABANDONED,
                    actor_type="system", source="system", outlet_id=r.outlet_id,
                    payload={"reason": "pickup_ttl_expired",
                             "ttl_minutes": settings.PICKUP_TTL_MINUTES,
                             # Records whether this abandonment took money with
                             # it, which is what distinguishes the two very
                             # different things this one event has always meant.
                             "was_paid": (r.payment_status or "").upper() == "PAID",
                             "refund_required": (r.payment_status or "").upper() == "PAID"},
                )
            # STOCK (033): an abandoned order's hold comes back. HELD-only, so
            # a paid-and-collected order's COMMITTED rows are left alone.
            from app.modules.carevo_customer.stock import StockService
            for r in rows:
                await StockService.release_for_order(
                    db, r.id, reason="ttl_abandoned")
            await db.commit()
            # PE Step 4: score terminal (abandoned) orders too, best-effort.
            for r in rows:
                try:
                    from app.modules.prediction.service import PredictionService
                    await PredictionService.compute_outcome(db, r.id)
                except Exception:
                    await db.rollback()
        return len(rows)

    @staticmethod
    async def expire_unclaimed_upi_orders(
        db: AsyncSession, *, outlet_id=None, order_id=None, customer_id=None
    ) -> int:
        """Cancel direct-UPI orders nobody claimed to have paid (035).

        The counterpart to _expire_stale_pickups, for a state that sweeper
        cannot see: an unclaimed UPI order sits in CREATED, and CREATED is
        absent from _LIVE_STATUSES by design.

        Without this the order would sit forever holding stock until the
        600-second reservation TTL reclaimed it, leaving a permanent CREATED
        row that still counted against the customer's one-open-order cap —
        so a customer who opened checkout and changed their mind would be
        locked out of ordering until someone noticed.

        NO REFUND IS FLAGGED, on either axis. The defining property of the rows
        this matches is that nobody ever said money was sent: payment_claimed_at
        IS NULL. A claimed order is excluded here and expires through the
        acceptance deadline instead, which DOES flag a manual refund.

        Driven from the same check-on-read slot as every other sweep, and
        commits its own maintenance UPDATE. Idempotent.
        """
        clauses = [
            "payment_mode = :mode",
            "upper(coalesce(status, '')) = 'CREATED'",
            "payment_claimed_at IS NULL",
            "created_at < now() - make_interval(secs => :w)",
        ]
        params: dict = {"mode": PAY_UPI_MANUAL, "w": UPI_PAY_WINDOW_SECONDS}
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)
        if order_id is not None:
            clauses.append("id = :iid")
            params["iid"] = str(order_id)
        # Per-CUSTOMER scope, so the global open-order cap can release a lapsed
        # order without waiting for the outlet it was placed at to poll. See
        # the call in _open_pickup_order_id.
        if customer_id is not None:
            clauses.append("customer_id = :cid")
            params["cid"] = str(customer_id)

        rows = (await db.execute(text(
            "UPDATE customer_orders SET status = 'CANCELLED', updated_at = now() "
            "WHERE " + " AND ".join(clauses)
            + " RETURNING id, outlet_id"
        ), params)).fetchall()
        if not rows:
            return 0

        from app.modules.carevo_customer.stock import StockService
        for r in rows:
            await pe.write_event(
                db, r.id, pe.ORDER_ABANDONED,
                actor_type="system", source="system", outlet_id=r.outlet_id,
                payload={"reason": "upi_pay_window_expired",
                         "window_seconds": UPI_PAY_WINDOW_SECONDS,
                         "was_paid": False, "refund_required": False},
            )
            # The hold comes back: nothing was claimed, nothing was cooked, and
            # these units are still HELD because only a claim commits them.
            await StockService.release_for_order(
                db, r.id, reason="upi_pay_window_expired")
        await db.commit()
        logger.info("cancelled %s unclaimed direct-UPI order(s)", len(rows))
        return len(rows)

    @staticmethod
    async def _generate_pickup_code(
        db: AsyncSession, outlet_id, *, sweep: bool = True
    ) -> str:
        """Allocate a code unique among this outlet's live orders.

        `sweep=False` SKIPS the stale-pickup sweep, and exists because that
        sweep COMMITS (_expire_stale_pickups ends with db.commit() whenever it
        matches a row).

        That commit is harmless where this is called from mark_paid, which is
        about to commit anyway. It is NOT harmless inside
        AcceptanceService.accept: there the caller is mid-transaction holding
        the acceptance CAS, the stock commit and — for a direct-UPI order — the
        payment record, and a commit here splits them. A crash in the gap would
        leave an order accepted and paid with no pickup code, which cannot be
        collected, or the code written against a payment that later rolled
        back.
        #
        Skipping the sweep costs nothing at that call site: accept is reached
        from GET /pos/orders, whose very first action is the same sweep, so any
        stale code has already been freed moments earlier. Uniqueness is still
        enforced by the partial unique index (033) and by the retry in
        _assign_pickup_code.
        """
        # Free up any expired codes for this outlet first.
        if sweep:
            await CarevoService._expire_stale_pickups(db, outlet_id=outlet_id)
        # Digits 2-9 only: no visually ambiguous chars (0/O, 1/I/l) and easy to
        # type on a numeric keypad at verify time. 8^6 = 262k codes, and
        # uniqueness is only needed among an outlet's LIVE orders (a handful).
        # Existing issued codes are unaffected — this only changes new ones.
        alphabet = "23456789"
        for _ in range(30):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            # Unique among LIVE orders for this outlet. ABANDONED is excluded so
            # an expired order's code is immediately reusable.
            row = (await db.execute(text("""
                SELECT 1 FROM customer_orders
                WHERE outlet_id = :oid AND pickup_code = :code
                  AND status NOT IN ('COMPLETED','CANCELLED','ABANDONED')
                LIMIT 1
            """), {"oid": str(outlet_id), "code": code})).first()
            if not row:
                return code
        raise HTTPException(status_code=500, detail="Could not allocate pickup code")

    @staticmethod
    async def _assign_pickup_code(
        db: AsyncSession, order, *, sweep: bool = True
    ) -> str:
        """Allocate a code and survive losing the race for it (migration 033).

        _generate_pickup_code above checks-then-returns, with no lock between
        the two, so two concurrent payments at one outlet could be handed the
        same code. Migration 033 adds a partial UNIQUE index that now REFUSES
        the second one — turning a silent collision into an IntegrityError,
        which is strictly better but still has to be handled.

        Handled by retrying: generate, try to write, and on a unique violation
        generate a fresh code and try again. The retry is cheap (8^6 space, a
        handful of live orders per outlet) and the loop is bounded, so the
        failure mode is a clean 500 rather than an infinite spin.

        Returns the code that actually committed.
        """
        from sqlalchemy.exc import IntegrityError

        for _ in range(5):
            code = await CarevoService._generate_pickup_code(
                db, order.outlet_id, sweep=sweep)
            try:
                # A SAVEPOINT, so a unique violation rolls back only this
                # attempt and leaves the caller's transaction — which is
                # carrying the PAID transition — intact. Without the nested
                # block the first collision would abort the payment too.
                async with db.begin_nested():
                    await db.execute(text(
                        "UPDATE customer_orders SET pickup_code = :c "
                        "WHERE id = :id"),
                        {"c": code, "id": str(order.id)})
                order.pickup_code = code
                return code
            except IntegrityError:
                logger.info(
                    "pickup code %s collided at outlet %s; regenerating",
                    code, order.outlet_id)
                continue
        raise HTTPException(status_code=500,
                            detail="Could not allocate a unique pickup code")

    @staticmethod
    async def mark_paid(
        db: AsyncSession,
        order: CustomerOrder,
        *,
        gateway_payment_id: Optional[str] = None,
        gateway_signature: Optional[str] = None,
        method: Optional[str] = None,
        raw_payload: Optional[dict] = None,
        amount_paise: Optional[int] = None,
    ) -> CustomerOrder:
        """Idempotent PAID transition shared by webhook + simulate.

        Refuses to reopen a FINISHED order. The two idempotency checks below
        both key on the PAYMENT, never on the order, so before this guard
        existed any order whose payment had not settled could be driven to
        PAID no matter what its status was — a late or replayed webhook could
        flip a CANCELLED order back to live and mint it a pickup code. See
        _TERMINAL_STATUSES.

        Ordering here is deliberate and load-bearing: the guard is THIRD, after
        both idempotency returns, so genuine retries are untouched. A duplicate
        webhook carrying a known payment id still short-circuits on the first
        check, and a second webhook for an already-PAID order still returns on
        the second — including when that order has since been COMPLETED, which
        is the common case and must not start logging warnings. Only an order
        that is finished AND unpaid reaches the guard, which is precisely the
        resurrection case and nothing else.
        """
        # PAY AT PICKUP IS NOT A GATEWAY PATH (migration 034).
        #
        # Checked FIRST, before the idempotency returns, because the answer is
        # "do nothing" regardless of what the payment looks like.
        #
        # Money for these orders arrives at the counter and is recorded by
        # record_pickup_payment, which deliberately does not reuse this
        # function. Nothing should ever reach here with one — no gateway order
        # is created for a pay-at-pickup order, so the gateway has no id to
        # call back about, and the webhook's own lookup by gateway_order_id
        # cannot match a row that does not exist.
        #
        # It is refused anyway, because the webhook ALSO resolves orders by an
        # id taken straight off the wire (`evt.our_order_id`). That path is
        # signature-gated and a real gateway would never name one of these, but
        # "unreachable" and "harmless if reached" are different claims, and
        # this is the one place they can be made the same. If it were reached,
        # mark_paid would set status='PAID' on an order that may be READY —
        # dragging it backwards — and accrue points a second time at handover.
        #
        # /payment/simulate also funnels here, so this closes that too: on a
        # stub deployment a customer could otherwise mark their own
        # pay-at-pickup order paid and collect without paying.
        #
        # LOUD, because every way of getting here is either a replay worth
        # investigating or a bug in our own code.
        pickup_mode = await db.scalar(text(
            "SELECT payment_mode FROM customer_orders WHERE id = :id"),
            {"id": str(order.id)})
        if (pickup_mode or "") in _NON_GATEWAY_METHODS:
            logger.warning(
                "mark_paid REFUSED: order %s is %s and settles outside the "
                "gateway, not through it. gateway_payment_id=%s method=%s "
                "status=%s payment_status=%s",
                order.id, pickup_mode, gateway_payment_id, method, order.status,
                order.payment_status)
            # Returned unchanged rather than raised, matching the terminal
            # guard below: the webhook caller must still answer the gateway 200
            # or it retries forever, and it reports the real payment_status so
            # the caller can see nothing was applied.
            return order

        # Idempotency on gateway_payment_id.
        if gateway_payment_id:
            existing = (await db.execute(text("""
                SELECT customer_order_id FROM payment_transactions
                WHERE gateway_payment_id = :pid AND status = 'PAID' LIMIT 1
            """), {"pid": gateway_payment_id})).first()
            if existing:
                res = await db.execute(
                    select(CustomerOrder).where(CustomerOrder.id == existing[0])
                )
                return res.scalars().first() or order

        if order.payment_status == "PAID":
            return order  # already settled

        current = (order.status or "").upper()
        if current in _TERMINAL_STATUSES:
            # Loud on purpose. Reaching here means money may have moved against
            # an order the customer was told was over, so it is either a very
            # late gateway callback or a replay worth investigating — and the
            # refund, if one is owed, is a human decision made off-app.
            logger.warning(
                "mark_paid REFUSED: order %s is %s (terminal) and cannot be "
                "reopened by a payment. gateway_payment_id=%s method=%s "
                "payment_status=%s raw_payload=%s",
                order.id, current, gateway_payment_id, method,
                order.payment_status,
                json.dumps(raw_payload, default=str) if raw_payload else None,
            )
            # A GATEWAY payment that lands after the order (or its stock hold)
            # is already over is real money CareVo now holds against nothing —
            # the customer never got a pickup code and the kitchen was never
            # told to cook. That is not "nothing happened", so it goes into
            # the SAME refund_required queue a payment-after-rejection does
            # (see reject_order) rather than being logged and dropped.
            #
            # payment_mode gate mirrors the non-gateway refusal above: a
            # pay-at-pickup/UPI order never has a gateway payment to begin
            # with, so this can only be reached by a genuine stray gateway
            # callback — not by the counter-payment paths those modes use.
            if (pickup_mode or "") not in _NON_GATEWAY_METHODS:
                await db.execute(text("""
                    UPDATE customer_orders
                       SET refund_required = true,
                           refund_reason = 'late_payment_after_expiry',
                           refund_flagged_at = now()
                     WHERE id = :id AND NOT refund_required
                """), {"id": str(order.id)})
                await db.commit()
            # Returned unchanged rather than raised: the webhook caller must
            # still answer the gateway 200, or it retries this forever. The
            # caller sees an order that is plainly not PAID and reports that,
            # and mints no pickup code.
            return order

        # UNDERPAID (Cashfree hardening). Only checked when the caller HAS an
        # amount to check — the stub's /payment/simulate passes none, so this
        # is a no-op there and every existing dev/test flow through it is
        # unaffected. A short payment is not "no payment" and not "the right
        # payment either", so it is neither silently accepted nor treated as
        # the late-after-expiry case above: the order stays exactly as it
        # was (no PAID, no code) and is flagged for a human to reconcile.
        if amount_paise is not None:
            total_paise = int(round(float(order.total_amount) * 100))
            if amount_paise < total_paise:
                logger.warning(
                    "mark_paid REFUSED: order %s received %d paise, short of "
                    "its %d paise total. Flagged, NOT marked PAID. "
                    "gateway_payment_id=%s", order.id, amount_paise,
                    total_paise, gateway_payment_id)
                await db.execute(text("""
                    UPDATE customer_orders
                       SET payment_amount_mismatch = true,
                           payment_amount_mismatch_at = now()
                     WHERE id = :id
                """), {"id": str(order.id)})
                await db.commit()
                return order

        gw = get_gateway()
        pay_id = gateway_payment_id or gw.make_payment_id()

        # Find the pending transaction (created at order time) or make a new one.
        res = await db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.customer_order_id == order.id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        txn = res.scalars().first()
        if txn is None:
            txn = PaymentTransaction(customer_order_id=order.id, amount=order.total_amount)
            db.add(txn)

        sig = gateway_signature or gw.sign_payment(txn.gateway_order_id or "", pay_id)
        txn.gateway = txn.gateway or gw.name
        txn.gateway_payment_id = pay_id
        txn.gateway_signature = sig
        txn.method = method or txn.method or "upi"
        txn.status = "PAID"
        txn.raw_payload = raw_payload
        txn.updated_at = datetime.now(timezone.utc)

        order.payment_status = "PAID"
        order.status = "PAID"
        if not order.pickup_code:
            # Collision-safe since migration 033 added the partial unique
            # index: this retries on a unique violation inside a SAVEPOINT, so
            # losing the race for a code cannot take the payment down with it.
            await CarevoService._assign_pickup_code(db, order)
        order.updated_at = datetime.now(timezone.utc)

        # --- scheduled pickup: take the hold IN THIS TRANSACTION (031) -------
        # A held order must never be visible to the restaurant, not even for the
        # width of one poll. Setting release_at anywhere after this commit would
        # leave exactly that window open, so the hold is taken atomically with
        # the PAID transition itself.
        #
        # The value seeded here is requested_pickup_at — the LATEST possible
        # release, i.e. the most conservative hold there is. It is deliberately
        # not the real answer: mu_ready_s comes from the twin, and the twin is
        # recomputed after this commit (recompute_twin commits internally, so it
        # cannot join this transaction). Every later derivation can only move
        # release_at EARLIER, so the invariant "never released before its true
        # release moment" holds at every instant, including the moments between.
        #
        # If the refinement never runs at all the order still releases — at
        # pickup time, with the customer waiting mu minutes. Degraded, not lost,
        # and self-healing: the poller and the check-on-read both re-derive.
        requested_pickup_at = (await db.execute(text(
            "SELECT requested_pickup_at FROM customer_orders WHERE id = :id"
        ), {"id": str(order.id)})).scalar()
        held = (requested_pickup_at is not None
                and requested_pickup_at > datetime.now(timezone.utc))
        if held:
            await db.execute(text(
                "UPDATE customer_orders SET release_at = :r WHERE id = :id"),
                {"r": requested_pickup_at, "id": str(order.id)})
            # The durable record of the pending release, written in the SAME
            # transaction as the hold so a restart between the two is not a
            # state that exists. auto_advance_schedule (028) already is "one
            # order's next stage and when it is due" and already survives a
            # redeploy, so scheduled pickup reuses it rather than adding a
            # second table with the same shape.
            #
            # kind='release' is what stops process_due_auto_advances treating
            # this as roster automation: release rows ignore
            # AUTO_ADVANCE_ROSTER_ORDERS entirely and drive exactly one advance.
            await db.execute(text("""
                INSERT INTO auto_advance_schedule
                    (order_id, next_stage, due_at, kind, updated_at)
                VALUES (:oid, 'RECEIVED', :due, 'release', now())
                ON CONFLICT (order_id)
                DO UPDATE SET next_stage = 'RECEIVED', due_at = EXCLUDED.due_at,
                              kind = 'release', updated_at = now()
            """), {"oid": str(order.id), "due": requested_pickup_at})

        # FR-E1: ORDER_PAID in the same transaction as the PAID transition.
        await pe.write_event(
            db, order.id, pe.ORDER_PAID,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            payload={"method": method or "upi_manual"},
        )
        # PE Step 2: the owner has a single app and won't tap kitchen states, so
        # the system INFERS the kitchen lifecycle. Payment confirmation is taken
        # as acceptance + prep start. source='inferred' → excluded from kitchen
        # training as ground truth (FR-E2), but anchors the twin/prediction.
        #
        # NOT FOR A HELD ORDER (031). For a scheduled pickup these two are
        # emitted at RELEASE instead — see _release_held_order. Payment is no
        # longer a truthful proxy for "the kitchen started" when the kitchen is
        # deliberately not being told for another three hours, and the lie is
        # not cosmetic: compute_outcome derives actual_prep_s as
        # (ready_at - prep_started_at), so a held order would record a prep time
        # of hours. That feeds refresh_outlet_reliability's median_prep_s and
        # trusted_order_count, and trusted_order_count feeds straight back into
        # sigma — the first scheduled orders would poison the very statistic the
        # engine uses to size its own uncertainty.
        # ALSO not for a MANUAL-acceptance outlet (migration 032). There, the
        # same reasoning applies for a different cause: nobody has accepted the
        # order yet, so inferring "accepted, and cooking started" from payment
        # would be a plain untruth — and the same compute_outcome arithmetic
        # would charge the restaurant's median_prep_s with however long the
        # tablet sat unanswered. The events are emitted on the Accept tap
        # instead (AcceptanceService.accept), in the identical pair and order.
        #
        # An AUTO outlet — every outlet until someone opts in — takes this
        # branch exactly as before.
        from app.modules.carevo_customer.acceptance import AcceptanceService
        manual = await AcceptanceService.is_manual(db, order.outlet_id)

        if not held and not manual:
            await pe.write_event(
                db, order.id, pe.ORDER_ACCEPTED,
                actor_type="system", source="inferred", outlet_id=order.outlet_id,
                payload={"derived_from": "mark_paid"},
            )
            await pe.write_event(
                db, order.id, pe.PREP_STARTED,
                actor_type="system", source="inferred", outlet_id=order.outlet_id,
                payload={"derived_from": "mark_paid"},
            )

        # Manual + immediate: start the acceptance clock in THIS transaction,
        # atomically with the PAID transition. A held order does NOT start its
        # clock here — _release_held_order does it at release, because a pickup
        # three hours out would otherwise expire before the kitchen saw it.
        if manual and not held:
            await AcceptanceService.begin_awaiting(db, order, reason="payment")

        # STOCK (migration 033): the hold taken at order creation becomes a
        # spend, in the same transaction as the PAID transition.
        #
        # The LATE-WEBHOOK case is handled first. If the sweeper (or a cancel)
        # already gave the units back and the payment then landed, the money is
        # real — so the order either gets its stock back or is cancelled and
        # refunded. Quietly proceeding would promise food the restaurant does
        # not have, which is the one outcome worse than a refund.
        from app.modules.carevo_customer.stock import StockService
        if not await StockService.rereserve_for_order(db, order.id):
            logger.warning(
                "order %s paid but its released stock could not be re-taken; "
                "cancelling and flagging a refund", order.id)
            order.status = "CANCELLED"
            order.refund_required = True
            order.refund_reason = "stock_gone_after_payment"
            order.refund_flagged_at = datetime.now(timezone.utc)
            await pe.write_event(
                db, order.id, pe.ORDER_REJECTED,
                actor_type="system", source="system", outlet_id=order.outlet_id,
                payload={"reason": "stock_gone_after_payment",
                         "refund_required": True},
            )
            await db.commit()
            await db.refresh(order)
            await CarevoService._broadcast_status(order, db)
            return order
        await StockService.commit_for_order(db, order.id)

        # Loyalty accrual (migration 010), in the SAME transaction as the PAID
        # transition: points are earned iff the payment is recorded, and the two
        # can never diverge through a partial failure.
        await CarevoService._accrue_points(db, order)

        await db.commit()
        await db.refresh(order)

        await CarevoService._broadcast_status(order, db)

        # PE Step 4 (shadow mode): compute the order twin once accepted. Runs in
        # its own transaction AFTER payment is committed, wrapped so a prediction
        # failure can never roll back or break the payment (FR-M1: promise only
        # after ORDER_ACCEPTED, which mark_paid just emitted).
        try:
            from app.modules.prediction.service import PredictionService
            await PredictionService.recompute_twin(db, order.id)
        except Exception:
            await db.rollback()

        # Scheduled pickup (031): now that a twin exists, refine the conservative
        # hold taken above down to its real value and record the decision. Same
        # best-effort contract as everything else after the commit — a failure
        # here leaves the order held until pickup time, which is safe.
        if held:
            try:
                await CarevoService.refresh_scheduled_releases(db, order_id=order.id)
            except Exception:
                await db.rollback()

        # Roster-scoped auto-progression (testing only). If the feature is on and
        # this order's phone is a tester, schedule the automatic RECEIVED ->
        # PREPARING -> READY advances (READY then chains into the existing
        # auto-pickup) so the tester needs zero restaurant-side taps. NON-roster
        # orders are never scheduled, so a real customer's order is untouched.
        # Lazy import breaks the cycle (testing_dashboard imports CarevoService);
        # best-effort so a scheduling failure can never affect the committed
        # payment. Only the true PAID transition reaches here — the idempotent
        # early-returns above mean a retried webhook does not re-schedule.
        #
        # SKIPPED while held: auto_advance_schedule is keyed on order_id, so a
        # roster row would overwrite the release row that refresh_scheduled_
        # releases just wrote and the order would walk into the kitchen
        # immediately — the exact opposite of being held. A tester's scheduled
        # order picks the roster chain back up at release instead, so tester
        # automation still covers this path end to end.
        if not held:
            try:
                from app.modules.testing_dashboard.service import TestingService
                await TestingService.maybe_schedule_auto_advance(db, order)
            except Exception:
                pass
        return order

    # Rejecting is allowed right up until the food is ready. Past READY the
    # order is made and sitting on the counter — "we can't do this one" is no
    # longer true, and the customer may already be walking over.
    REJECTABLE_STATUSES = {"PAID", "RECEIVED", "PREPARING"}

    # Statuses at or past which an order's COMPOSITION can no longer change.
    # Expressed as a deny-list rather than an allow-list on purpose: the
    # question is "has the kitchen finished or has the order ended", and a
    # status nobody has thought of yet should default to still-changeable
    # rather than being silently blocked.
    #
    # Same boundary as REJECTABLE_STATUSES for the same reason — once the food
    # is made, telling the customer an item "won't be prepared" is false: it
    # already was. Past that point the remedy is a refund conversation, not an
    # availability notice.
    COMPOSITION_LOCKED_STATUSES = {
        "READY", "COMPLETED", "PICKED_UP", "CANCELLED", "ABANDONED",
    }

    @staticmethod
    def _assert_composition_open(status: Optional[str], *, count: int = 1) -> None:
        """Reject an item-unavailable action once the order is READY or over.

        Server-side half of the cutoff. The owner app also disables the control,
        but the UI is never the enforcement point — a stale screen, a replayed
        request or a second device would otherwise walk straight past it.
        """
        s = (status or "").upper()
        if s not in CarevoService.COMPOSITION_LOCKED_STATUSES:
            return
        noun = "This item" if count == 1 else "These items"
        raise HTTPException(
            status_code=409,
            detail=(
                f"{noun} can no longer be marked unavailable — the order is "
                f"already {s.lower()}."
                if s != "READY" else
                f"{noun} can no longer be marked unavailable — the order is "
                "already ready for pickup."
            ),
        )

    @staticmethod
    async def auto_receive(db: AsyncSession, order: CustomerOrder) -> CustomerOrder:
        """PAID -> RECEIVED with no human gate.

        There is no Accept step by design: a paid order is accepted. Staff get a
        push and can REJECT if something is genuinely wrong, but the order is
        never parked waiting for someone to notice it.

        mark_paid is left completely untouched — it still emits the inferred
        ORDER_ACCEPTED/PREP_STARTED the prediction engine anchors on, at exactly
        the same moment it always did. This only moves the visible status on.
        """
        if (order.status or "").upper() != "PAID":
            return order  # already moved on, or never paid
        return await CarevoService.advance_status(db, order.id, "RECEIVED")

    @staticmethod
    async def reject_order(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, reason: Optional[str] = None, actor_user_id: Optional[uuid.UUID] = None,
        unreachable: bool = False, upi_outcome: Optional[str] = None,
    ) -> dict:
        """Staff refuse a paid order -> CANCELLED + ORDER_REJECTED.

        ORDER_REJECTED is a distinct event on purpose. ORDER_ABANDONED already
        exists and means the TTL sweeper expired an order nobody paid for;
        PAYMENT_FAILED means the gateway declined. This one is a human saying
        no to money already taken — the only one of the three that obliges a
        refund, and the only one worth surfacing to the customer as a decision
        rather than an accident.

        Refunds are deliberately OUT of scope: handled manually outside the app.
        """
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")

        current = (order.status or "").upper()
        if current == "CANCELLED":
            # Idempotent: a double-tap is not an error.
            return {"order_id": order.id, "status": current, "already": True}

        # CREATED is rejectable for a PAY-AT-PICKUP order and nothing else
        # (migration 034).
        #
        # Scoped that tightly on purpose. A pay-at-pickup order sits in CREATED
        # for its whole confirmation window — that IS the state staff decide
        # on, and "we called and they did not answer" has to be expressible.
        # But adding CREATED to REJECTABLE_STATUSES wholesale would also let
        # staff cancel a PREPAID order while the customer was mid-checkout, out
        # from under a Cashfree sheet that was already open. So the widening is
        # per-order, keyed on the order's own payment_mode, and the module-level
        # set keeps its exact current meaning.
        mode_row = (await db.execute(text(
            "SELECT payment_mode, payment_claimed_at FROM customer_orders "
            "WHERE id = :id"), {"id": str(order_id)})).first()
        pay_mode = mode_row[0] if mode_row else None
        claimed_at = mode_row[1] if mode_row else None
        pay_at_pickup = (pay_mode or "") == PAY_AT_PICKUP
        upi_manual = (pay_mode or "") == PAY_UPI_MANUAL
        rejectable = set(CarevoService.REJECTABLE_STATUSES)
        # Both non-gateway modes sit in CREATED while awaiting a human, so both
        # must be rejectable from there. A PREPAID order in CREATED still is
        # not — that would cancel a checkout the customer is mid-way through.
        if pay_at_pickup or upi_manual:
            rejectable.add("CREATED")

        if current not in rejectable:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This order is already ready for pickup and can no longer be "
                    "rejected." if current in ("READY", "COMPLETED")
                    else f"An order in {current} cannot be rejected."
                ),
            )

        order.status = "CANCELLED"
        order.updated_at = datetime.now(timezone.utc)

        # A rejected PAID order owes the customer money (migration 032). This
        # is the flag's primary writer and the reason it exists: before it, the
        # only record was an ORDER_REJECTED event nobody queried, so "who are
        # we paying back" had to be reconstructed from the event log by hand.
        #
        # Guarded on payment_status so rejecting an unpaid order — which the
        # REJECTABLE_STATUSES gate permits — does not flag a refund for money
        # that never arrived.
        # ONLY A GATEWAY PAYMENT CAN ENTER THE GATEWAY REFUND QUEUE.
        #
        # `payment_status == 'PAID'` was the whole condition, and it stopped
        # being sufficient the moment a payment could arrive outside Cashfree.
        # An ACCEPTED direct-UPI order is PAID — accept is what records the
        # money — so rejecting one with cannot_make flagged refund_required and
        # the order appeared in /admin/orders/refund-due, a queue of refunds
        # CareVo is being asked to issue for money it never received and cannot
        # reverse. The same is true of a collected pay-at-pickup order.
        #
        # refund_required now means what its comment always said: a GATEWAY
        # payment has to go back out through the gateway. The restaurant's own
        # obligation is manual_refund_due (035), set below.
        was_paid = (order.payment_status or "").upper() == "PAID"
        is_gateway = (pay_mode or PAY_PREPAID) == PAY_PREPAID
        if was_paid and is_gateway and not order.refund_required:
            order.refund_required = True
            order.refund_reason = "order_rejected"
            order.refund_flagged_at = datetime.now(timezone.utc)

        # Settle the ACCEPTANCE axis in the SAME transaction as the status, for
        # a manual-mode order. If these were separate, the deadline sweeper
        # could expire an order a human had just rejected and the order would
        # carry two terminal causes. Returns False for an auto-mode order
        # (acceptance_state NULL), which is the common case and not an error.
        # STOCK (033): give the units back. Only HELD rows move, so this is
        # idempotent and a COMMITTED reservation on a paid order is untouched —
        # the food was made, the stock is genuinely gone.
        from app.modules.carevo_customer.stock import StockService
        await StockService.release_for_order(db, order.id, reason="rejected")

        from app.modules.carevo_customer.acceptance import AcceptanceService
        was_awaiting = await AcceptanceService.cas_reject(db, order.id)
        if was_awaiting:
            # Any decision proves the outlet is answering again.
            await AcceptanceService._reset_expiries(db, order.outlet_id)

        # COULD NOT REACH THEM (migration 034). A distinct outcome from "we
        # will not make this": the restaurant did not refuse the order, it
        # failed to get hold of the customer. Recorded on call_state so the
        # difference survives on the row, and as its own event below so it
        # survives in the log.
        #
        # Guarded on pay_at_pickup because call_state is NULL for a prepaid
        # order and its CHECK constraint permits only the three call values —
        # writing one onto a prepaid order would be meaningless, not just
        # untidy.
        if unreachable and pay_at_pickup:
            await db.execute(text(
                "UPDATE customer_orders SET call_state = 'UNREACHABLE' "
                "WHERE id = :id"), {"id": str(order_id)})

        # ------------- DIRECT UPI: WHICH KIND OF NO THIS WAS (035) ----------
        #
        # Two outcomes that look identical in `status` (both CANCELLED) and are
        # opposites in every way that matters:
        #
        #   not_received — the money is NOT in the restaurant's UPI app. The
        #       customer claimed something that did not happen, so the strike
        #       is theirs and NOTHING is owed. Flagging a refund here would be
        #       paying out against a payment that was never made.
        #
        #   cannot_make  — the money IS there and the restaurant cannot cook
        #       it. The customer is owed their money back, by the restaurant,
        #       UPI to UPI. manual_refund_due, never refund_required: CareVo
        #       was not in the path and cannot reverse it, so it must not
        #       appear in /admin/orders/refund-due as though it could.
        #
        # Only meaningful once a claim exists. Rejecting an unclaimed UPI order
        # is an ordinary refusal — no money was asserted, so neither a strike
        # nor a refund applies.
        # 'not_received' IS A CONTRADICTION ONCE THE MONEY IS RECORDED.
        #
        # Accepting a direct-UPI order IS the payment confirmation: a human
        # looked at their own UPI app and said the amount was there, and
        # payment_status became PAID on the strength of that. Saying
        # "not received" afterwards asserts the opposite of something this
        # restaurant already asserted — and it would strike the CUSTOMER for
        # it, on an order whose money the restaurant is holding.
        #
        # Refused rather than reinterpreted. If the restaurant has changed its
        # mind about an order it accepted, that is cannot_make: cancel it and
        # give the money back. The message says so, because the staff member
        # has to pick the other button and should know which.
        if (upi_manual and upi_outcome == "not_received"
                and (order.payment_status or "").upper() == "PAID"):
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "PAYMENT_ALREADY_RECORDED",
                    "message": (
                        "You already confirmed this payment when you accepted "
                        "the order. If you cannot make it, use \"Can't make "
                        "this\" and refund the customer."
                    ),
                },
            )

        if upi_manual and claimed_at is not None and upi_outcome:
            if upi_outcome == "not_received":
                await db.execute(text(
                    "UPDATE customers SET false_claim_count = "
                    "false_claim_count + 1 WHERE id = :cid"),
                    {"cid": str(order.customer_id)})
                await pe.write_event(
                    db, order.id, pe.PAYMENT_NOT_RECEIVED,
                    actor_type="staff", source="tap", outlet_id=order.outlet_id,
                    actor_id=actor_user_id,
                    payload={"amount": float(order.total_amount or 0)},
                )
            elif upi_outcome == "cannot_make":
                await db.execute(text("""
                    UPDATE customer_orders
                       SET manual_refund_due = true,
                           manual_refund_reason = :r
                     WHERE id = :id
                """), {"r": reason or "Restaurant could not make the order",
                       "id": str(order_id)})
                await pe.write_event(
                    db, order.id, pe.MANUAL_REFUND_DUE,
                    actor_type="staff", source="tap", outlet_id=order.outlet_id,
                    actor_id=actor_user_id,
                    payload={"amount": float(order.total_amount or 0),
                             "reason": "cannot_make"},
                )

        await pe.write_event(
            db, order.id, pe.ORDER_REJECTED,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            actor_id=actor_user_id,
            payload={"reason": reason, "from_status": current,
                     "was_awaiting_acceptance": was_awaiting,
                     "refund_required": bool(was_paid),
                     # 034: which kind of no this was.
                     "unreachable": bool(unreachable and pay_at_pickup),
                     "payment_mode": pay_mode or "PREPAID"},
        )
        if unreachable and pay_at_pickup:
            await pe.write_event(
                db, order.id, pe.ORDER_CALL_UNREACHABLE,
                actor_type="staff", source="tap", outlet_id=order.outlet_id,
                actor_id=actor_user_id,
                payload={"from_status": current},
            )
        await db.commit()
        await db.refresh(order)

        # Same choke point every other transition uses, so the customer's WS
        # banner and the FCM push both fire from one place.
        await CarevoService._broadcast_status(order, db)

        # Stop the OTHER devices ringing. Only meaningful when this reject
        # settled a pending acceptance — in auto mode nothing was alarming.
        if was_awaiting:
            await AcceptanceService._announce_resolved(db, order, outcome="rejected")
        return {
            "order_id": order.id,
            "status": order.status,
            "already": False,
            "reason": reason,
        }

    @staticmethod
    async def _notify_kitchen_for_due_trains(
        db: AsyncSession, *, outlet_id=None
    ) -> int:
        """Check-on-read: push the kitchen for any TRAIN order now due to start.

        Same pattern as _expire_stale_pickups, and for the same reason — this
        deploy has no scheduler and Render's free tier sleeps, so "run at time
        T" is implemented as "check whether T has passed, on a read that
        happens often anyway" (GET /pos/orders). No Celery, no APScheduler, no
        worker process.

        Due when:  now() >= declared_arrival_at - prep_estimate - safety_buffer

        The prep estimate is NOT recomputed here — it is read from the order's
        twin (ready_sigma_s' sibling `inputs`), which predict_kitchen already
        produced. Building a second prep estimator was explicitly out of scope.

        Emits KITCHEN_START_NOTIFIED once per order. Idempotency is the event
        log itself: order_events is append-only and already the source of
        truth for every other transition, so "have we told them yet" is a
        NOT EXISTS against it rather than a new flag column.

        Does NOT touch status, PREP_STARTED, or anything else. Purely a push.
        """
        from app.modules.prediction.service import (
            DECLARED_ARRIVAL_MODES, KITCHEN_NOTIFY_SAFETY_BUFFER_S,
        )

        clauses = [
            # Metro joined train here in migration 029: both are DECLARED-arrival
            # modes, so both need the kitchen woken relative to a stated time
            # rather than a travel estimate. Left as an IN-list over the wire
            # values rather than a `declared_arrival_at IS NOT NULL` test alone,
            # so a future mode that merely happens to carry a time cannot start
            # silently triggering kitchen pushes.
            "co.transport_mode = ANY(:declared_modes)",
            "co.declared_arrival_at IS NOT NULL",
            "co.status = ANY(:live)",
            # Scheduled pickup wins (031). A customer can legitimately supply
            # both a declared train arrival and a chosen pickup time, and both
            # of these mechanisms decide WHEN THE KITCHEN STARTS. Firing both
            # would wake the kitchen twice, at two different moments, for one
            # order. release_at is the authority because it is the time the
            # customer explicitly asked to collect at, rather than one we
            # inferred from when their train gets in. declared_arrival_at is
            # still stored and still feeds predict_travel's customer_declared
            # leg — only the notification is suppressed.
            "co.release_at IS NULL",
            # Not already notified — the append-only log IS the flag.
            "NOT EXISTS (SELECT 1 FROM order_events e "
            " WHERE e.order_id = co.id AND e.event_type = 'KITCHEN_START_NOTIFIED')",
            # Due: arrival minus prep minus buffer has passed. COALESCE because
            # a twin may not exist yet for a very fresh order; falling back to 0
            # prep makes it fire at (arrival - buffer), i.e. later, never earlier.
            "now() >= co.declared_arrival_at"
            "        - make_interval(secs => COALESCE(t.prep_s, 0))"
            "        - make_interval(secs => :buf)",
        ]
        params = {"live": list(_LIVE_STATUSES),
                  "declared_modes": list(DECLARED_ARRIVAL_MODES),
                  "buf": KITCHEN_NOTIFY_SAFETY_BUFFER_S}
        if outlet_id is not None:
            clauses.append("co.outlet_id = :oid")
            params["oid"] = str(outlet_id)

        rows = (await db.execute(text(f"""
            SELECT co.id, co.outlet_id, co.declared_arrival_at,
                   COALESCE(t.prep_s, 0) AS prep_s
            FROM customer_orders co
            LEFT JOIN LATERAL (
                SELECT (ot.inputs ->> 'mu_ready_s')::numeric AS prep_s
                FROM order_twin ot WHERE ot.order_id = co.id
            ) t ON true
            WHERE {' AND '.join(clauses)}
        """), params)).fetchall()
        if not rows:
            return 0

        for r in rows:
            await pe.write_event(
                db, r.id, pe.KITCHEN_START_NOTIFIED,
                actor_type="system", source="system", outlet_id=r.outlet_id,
                payload={
                    "declared_arrival_at": r.declared_arrival_at.isoformat()
                    if r.declared_arrival_at else None,
                    "prep_estimate_s": float(r.prep_s or 0),
                    "safety_buffer_s": KITCHEN_NOTIFY_SAFETY_BUFFER_S,
                },
            )
        await db.commit()

        # Push after the event is committed: the event is the record, the push
        # is best-effort delivery of it. A push failure must not lose the fact
        # that the order became due.
        try:
            from app.modules.push.service import PushService
            for r in rows:
                await PushService.notify_outlet_train_due(db, r.id, r.outlet_id)
        except Exception:
            await db.rollback()
        return len(rows)

    # ------------------ Scheduled pickup release (migration 031) ------------
    #: A re-derived release_at that moves by less than this is not written and
    #: not logged. The engine's mu wobbles by a few seconds on every recompute
    #: as the backlog shifts, and the poller runs every few seconds — without a
    #: deadband, prediction_log would fill with rows recording that nothing
    #: happened, and the margin dataset would be mostly noise. 60s is well under
    #: the smallest margin change anyone would act on.
    RELEASE_REDERIVE_DEADBAND_S = 60

    @staticmethod
    async def _twin_prep_estimate(db: AsyncSession, order_id) -> Optional[tuple]:
        """(mu_ready_s, sigma_ready_s) for an order, refreshing a stale twin.

        Reads the SAME `order_twin.inputs` field _notify_kitchen_for_due_trains
        reads, for the same reason: predict_kitchen has already produced this
        number and a second prep estimator is explicitly out of scope.

        Unlike that function, this one will REFRESH a stale twin rather than
        COALESCE a miss to zero. The train path fires a notification and a stale
        estimate only makes it slightly early; here the number decides when a
        paid order reaches the kitchen at all, and an hours-old backlog estimate
        for a pickup three hours out is not worth acting on. Staleness is judged
        by the twin's own stale_after, the same test shadow_estimate uses.

        Returns None when no usable estimate exists — the caller then leaves the
        conservative hold in place rather than guessing.
        """
        sql = text("SELECT (inputs->>'mu_ready_s')::numeric AS mu, "
                   "       (inputs->>'sigma_ready_s')::numeric AS sigma, "
                   "       stale_after FROM order_twin WHERE order_id = :o")
        row = (await db.execute(sql, {"o": str(order_id)})).first()
        stale = row is None or (
            row.stale_after is not None
            and row.stale_after < datetime.now(timezone.utc))
        if stale:
            try:
                from app.modules.prediction.service import PredictionService
                await PredictionService.recompute_twin(db, order_id)
                row = (await db.execute(sql, {"o": str(order_id)})).first()
            except Exception:
                await db.rollback()
                row = (await db.execute(sql, {"o": str(order_id)})).first()
        if row is None or row.mu is None:
            return None
        return float(row.mu), float(row.sigma) if row.sigma is not None else None

    @staticmethod
    async def _log_release_decision(
        db: AsyncSession, *, order_id, outlet_id, mu, sigma,
        requested_pickup_at, release_at, decision: str, margin_s: int,
    ) -> None:
        """One prediction_log row for a release decision.

        THE SIXTH PREDICTOR. prediction_log.predictor is plain TEXT with no
        CHECK constraint, so this needed no migration — it slots in beside
        kitchen / travel / load / decision / promise using the same insert shape
        recompute_twin uses.

        This is the dataset that earns the right to shrink
        SCHEDULED_RELEASE_SAFETY_MARGIN_S. Every row carries the margin it was
        computed with and the decision it produced, and requested_pickup_at is
        on customer_orders, so the answer to "how early or late was the food
        against the time the customer picked" is one join against
        order_outcome.ready_at. Without the margin recorded per row, a later
        analysis could not tell which margin produced which outcome.

        Best-effort: a logging failure must never hold up a release.
        """
        from app.modules.prediction.service import RELEASE_MODEL_VERSION
        try:
            await db.execute(text("""
                INSERT INTO prediction_log
                    (order_id, outlet_id, predictor, model_version,
                     mu_seconds, sigma_seconds, features, output)
                VALUES (:o, :ou, 'release', :mv, :mu, :sig,
                        CAST(:f AS jsonb), CAST(:out AS jsonb))
            """), {
                "o": str(order_id), "ou": str(outlet_id),
                "mv": RELEASE_MODEL_VERSION,
                "mu": round(mu) if mu is not None else None,
                "sig": round(sigma) if sigma is not None else None,
                "f": json.dumps({
                    "requested_pickup_at": requested_pickup_at.isoformat()
                    if requested_pickup_at else None,
                    "safety_margin_s": margin_s,
                    "mu_ready_s": round(mu) if mu is not None else None,
                    "mu_source": "order_twin" if mu is not None else "none",
                }),
                "out": json.dumps({
                    "release_at": release_at.isoformat() if release_at else None,
                    "decision": decision,
                    "lead_s": round((requested_pickup_at - release_at).total_seconds())
                    if (requested_pickup_at and release_at) else None,
                }),
            })
        except Exception:
            logger.warning("release decision log failed for order %s", order_id)

    @staticmethod
    async def refresh_scheduled_releases(
        db: AsyncSession, *, outlet_id=None, order_id=None
    ) -> int:
        """Re-derive release_at for every held order in scope, and release the
        ones now due. Returns how many were released.

        THE single release implementation. Three things trigger it and none of
        them own it:

          * list_active_orders — the PRIMARY path. Check-on-read, exactly like
            _notify_kitchen_for_due_trains: the owner app polls /pos/orders
            every 15 seconds while the tablet is open, which is precisely when
            a release matters, since the whole purpose of releasing is to put
            the order on that tablet.
          * the background poller — the backstop. Render's free tier sleeps
            after ~15 minutes idle and takes the asyncio loop with it, so the
            poller alone would release late by however long the service napped.
          * mark_paid — once, to refine the conservative hold it just took.

        RE-DERIVED, NOT FROZEN. mu_ready_s at payment predicts the backlog at
        payment; for a pickup three hours out that number is meaningless by the
        time it matters. Each pass recomputes from the current twin, so a
        kitchen that got busy pushes its own releases earlier.

        The derivation can only move release_at earlier than the conservative
        seed mark_paid took (requested_pickup_at), never later than the
        customer's chosen time, so no refresh can make an order release late.
        """
        from app.modules.prediction.service import SCHEDULED_RELEASE_SAFETY_MARGIN_S

        clauses = ["release_at IS NOT NULL", "requested_pickup_at IS NOT NULL",
                   "status = ANY(:live)"]
        params = {"live": list(_LIVE_STATUSES)}
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)
        if order_id is not None:
            clauses.append("id = :iid")
            params["iid"] = str(order_id)

        # Retire holds on orders that left the live set without going through a
        # release. Two ways that genuinely happens, both reachable today:
        #
        #   * the customer turns up EARLY and staff serve them anyway —
        #     lookup_pickup matches any live order by its code, including a held
        #     one, so verify_pickup can complete it before its release moment;
        #   * staff reject the order from the testing dashboard, which can see
        #     held orders even though the owner queue cannot.
        #
        # In both cases _release_held_order is never reached (the select above
        # requires a live status), so without this the schedule row survives its
        # order forever and the poller re-examines it every few seconds for the
        # life of the deployment. The stale release_at is inert — nothing reads
        # it on a terminal order — but it is cleared too, so the admin timeline
        # does not show a hold that never happened.
        scope = ""
        if outlet_id is not None:
            scope += " AND outlet_id = :oid"
        if order_id is not None:
            scope += " AND id = :iid"
        await db.execute(text(
            "UPDATE customer_orders SET release_at = NULL "
            "WHERE release_at IS NOT NULL AND NOT (status = ANY(:live))" + scope
        ), params)
        await db.execute(text(
            "DELETE FROM auto_advance_schedule s WHERE s.kind = 'release' "
            "AND NOT EXISTS (SELECT 1 FROM customer_orders co "
            "                WHERE co.id = s.order_id "
            "                  AND co.release_at IS NOT NULL)"
        ))
        await db.commit()

        held = (await db.execute(text(
            "SELECT id, outlet_id, release_at, requested_pickup_at "
            "FROM customer_orders WHERE " + " AND ".join(clauses)
        ), params)).fetchall()
        if not held:
            return 0

        released = 0
        for row in held:
            try:
                estimate = await CarevoService._twin_prep_estimate(db, row.id)
                mu, sigma = estimate if estimate else (None, None)

                if mu is not None:
                    new_release = row.requested_pickup_at - timedelta(
                        seconds=mu + SCHEDULED_RELEASE_SAFETY_MARGIN_S)
                    # Never later than the customer's chosen time, whatever the
                    # engine says. A negative or absurd mu must not push a
                    # release past the moment they turn up to collect.
                    new_release = min(new_release, row.requested_pickup_at)
                    moved = abs((new_release - row.release_at).total_seconds())
                    if moved >= CarevoService.RELEASE_REDERIVE_DEADBAND_S:
                        await db.execute(text(
                            "UPDATE customer_orders SET release_at = :r "
                            "WHERE id = :id AND release_at IS NOT NULL"),
                            {"r": new_release, "id": str(row.id)})
                        await db.execute(text(
                            "UPDATE auto_advance_schedule SET due_at = :r, "
                            "updated_at = now() WHERE order_id = :id "
                            "AND kind = 'release'"),
                            {"r": new_release, "id": str(row.id)})
                        await CarevoService._log_release_decision(
                            db, order_id=row.id, outlet_id=row.outlet_id,
                            mu=mu, sigma=sigma,
                            requested_pickup_at=row.requested_pickup_at,
                            release_at=new_release, decision="held",
                            margin_s=SCHEDULED_RELEASE_SAFETY_MARGIN_S)
                        await db.commit()
                else:
                    new_release = row.release_at

                if new_release <= datetime.now(timezone.utc):
                    await CarevoService._release_held_order(
                        db, row.id, mu=mu, sigma=sigma,
                        requested_pickup_at=row.requested_pickup_at,
                        margin_s=SCHEDULED_RELEASE_SAFETY_MARGIN_S)
                    released += 1
            except Exception:
                # One bad order must never stop the rest of the sweep, and must
                # never break the owner's queue read that triggered it.
                logger.warning("scheduled release pass failed for order %s",
                               row.id, exc_info=True)
                try:
                    await db.rollback()
                except Exception:
                    pass
        return released

    @staticmethod
    async def _release_held_order(
        db: AsyncSession, order_id, *, mu=None, sigma=None,
        requested_pickup_at=None, margin_s: int = 0,
    ) -> Optional[CustomerOrder]:
        """Hand one held order to the restaurant. PAID -> RECEIVED, hold cleared.

        Ordering below is load-bearing:

          1. Clear release_at, write the DEFERRED inferred ORDER_ACCEPTED and
             PREP_STARTED, drop the schedule row — one transaction. Clearing
             FIRST is what makes the TTL exemption safe to leave the moment the
             order becomes live (see _expire_stale_pickups); doing it last would
             leave a released order still hidden if step 2 failed, which is the
             worse failure of the two.
          2. advance_status(RECEIVED) — the SAME function a staff tap, the
             webhook's auto_receive and the roster worker all call. It stamps
             updated_at=now(), which restarts the 45-minute pickup TTL at the
             release moment rather than at payment, and it broadcasts + pushes
             the customer through the one existing choke point.
          3. Tell the outlet, exactly as the payment webhook does for an
             immediate order — for a held order THIS is the moment the kitchen
             first learns the order exists, so the push belongs here.
          4. Hand off to the roster chain if applicable (testers only).
        """
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if order is None:
            return None
        # Anything not still PAID has been rejected, abandoned or advanced by a
        # human in the meantime; the hold is simply dropped.
        if (order.status or "").upper() != "PAID":
            await db.execute(text(
                "UPDATE customer_orders SET release_at = NULL WHERE id = :id"),
                {"id": str(order_id)})
            await db.execute(text(
                "DELETE FROM auto_advance_schedule WHERE order_id = :id "
                "AND kind = 'release'"), {"id": str(order_id)})
            await db.commit()
            return order

        await db.execute(text(
            "UPDATE customer_orders SET release_at = NULL WHERE id = :id"),
            {"id": str(order_id)})

        # MANUAL-ACCEPTANCE OUTLET: release means "the kitchen may now SEE it",
        # not "the kitchen has it". The hold is cleared and the schedule row
        # swapped from kind='release' to kind='acceptance', but the inferred
        # event pair is still withheld and the order does NOT advance to
        # RECEIVED — a human has to tap Accept, and the clock starts HERE
        # rather than at payment. Starting it at payment would expire a
        # three-hours-out pickup before the restaurant ever saw it, which is
        # the whole reason this branch exists.
        from app.modules.carevo_customer.acceptance import AcceptanceService
        if await AcceptanceService.is_manual(db, order.outlet_id):
            await AcceptanceService.begin_awaiting(
                db, order, reason="scheduled_release")
            await CarevoService._log_release_decision(
                db, order_id=order_id, outlet_id=order.outlet_id, mu=mu,
                sigma=sigma, requested_pickup_at=requested_pickup_at,
                release_at=datetime.now(timezone.utc), decision="released",
                margin_s=margin_s)
            await db.commit()
            await db.refresh(order)
            await AcceptanceService.send_first_alert(db, order)
            return order

        # The events mark_paid deliberately withheld. source='inferred' and the
        # same payload shape as the mark_paid pair, so nothing downstream has to
        # learn a new event type — only their TIMING changed, which is the whole
        # point: actual_prep_s is now measured from the real start of cooking.
        await pe.write_event(
            db, order_id, pe.ORDER_ACCEPTED,
            actor_type="system", source="inferred", outlet_id=order.outlet_id,
            payload={"derived_from": "scheduled_release",
                     "requested_pickup_at": requested_pickup_at.isoformat()
                     if requested_pickup_at else None},
        )
        await pe.write_event(
            db, order_id, pe.PREP_STARTED,
            actor_type="system", source="inferred", outlet_id=order.outlet_id,
            payload={"derived_from": "scheduled_release",
                     "mu_ready_s": round(mu) if mu is not None else None,
                     "safety_margin_s": margin_s},
        )
        await db.execute(text(
            "DELETE FROM auto_advance_schedule WHERE order_id = :id "
            "AND kind = 'release'"), {"id": str(order_id)})
        await CarevoService._log_release_decision(
            db, order_id=order_id, outlet_id=order.outlet_id, mu=mu, sigma=sigma,
            requested_pickup_at=requested_pickup_at,
            release_at=datetime.now(timezone.utc), decision="released",
            margin_s=margin_s)
        await db.commit()

        order = await CarevoService.advance_status(db, order_id, "RECEIVED")

        try:
            from app.modules.push.service import PushService
            await PushService.notify_outlet_new_order(db, order)
        except Exception:
            await db.rollback()

        # A tester who scheduled a pickup still gets hands-free progression —
        # the chain simply starts from PREPARING, because the release itself
        # just performed the RECEIVED step. Both of the roster gates (the
        # master switch and the roster membership check) still apply inside,
        # so a real customer's released order stops here and waits for a real
        # kitchen, which is the entire contract of the release.
        try:
            from app.modules.testing_dashboard.service import TestingService
            await TestingService.maybe_schedule_roster_chain(
                db, order, first_stage="PREPARING")
        except Exception:
            pass
        return order

    @staticmethod
    async def mark_payment_failed(
        db: AsyncSession,
        order: CustomerOrder,
        *,
        gateway_payment_id: Optional[str] = None,
        method: Optional[str] = None,
        raw_payload: Optional[dict] = None,
    ) -> CustomerOrder:
        """Record a gateway-reported payment failure.

        The mirror of mark_paid, and deliberately much smaller: nothing accrues,
        no pickup code is issued, no ORDER_ACCEPTED/PREP_STARTED is inferred.
        Only the payment outcome is recorded.

        Idempotent and one-way — never downgrades an order that is already PAID.
        Gateways retry, and retries arrive out of order; a late FAILED webhook
        for a payment that later succeeded must not un-pay a settled order.
        """
        if order.payment_status == "PAID":
            return order

        res = await db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.customer_order_id == order.id)
            .order_by(PaymentTransaction.created_at.desc())
        )
        txn = res.scalars().first()
        if txn is None:
            txn = PaymentTransaction(customer_order_id=order.id, amount=order.total_amount)
            db.add(txn)
        txn.gateway = txn.gateway or get_gateway().name
        if gateway_payment_id:
            txn.gateway_payment_id = gateway_payment_id
        txn.method = method or txn.method
        txn.status = "FAILED"
        txn.raw_payload = raw_payload
        txn.updated_at = datetime.now(timezone.utc)

        # The ORDER stays CREATED: the basket is still valid and the customer
        # can retry payment. Only payment_status carries the failure, so a
        # retry needs no resurrection logic.
        order.payment_status = "FAILED"
        order.updated_at = datetime.now(timezone.utc)

        # STOCK (033): the hold is DELIBERATELY NOT RELEASED here.
        #
        # A DEVIATION, recorded rather than silently taken. Releasing on
        # payment failure is the obvious symmetry with cancel/reject/expire,
        # and it is wrong for this path specifically: this order is still
        # LIVE and retryable (see the comment above — that is the existing and
        # intended design). Giving the units back would mean the customer taps
        # "Retry payment", the retry reserves again, and they are told
        # ITEM_SOLD_OUT for their own order — losing the sale to a hold that
        # was theirs seconds earlier.
        #
        # The hold is not leaked either. It carries expires_at, and
        # StockService.sweep_expired reclaims HELD rows on UNPAID orders, which
        # this now is. So a customer who retries within the window keeps their
        # units and a customer who walks away releases them on the clock —
        # which is what the TTL is for.

        await pe.write_event(
            db, order.id, pe.PAYMENT_FAILED,
            actor_type="system", source="webhook", outlet_id=order.outlet_id,
            payload={"method": method, "gateway_payment_id": gateway_payment_id},
        )
        await db.commit()
        await db.refresh(order)
        await CarevoService._broadcast_status(order, db)
        return order

    @staticmethod
    async def advance_status(db: AsyncSession, order_id: uuid.UUID,
                             target: Optional[str] = None,
                             *, outlet_id: Optional[uuid.UUID] = None) -> CustomerOrder:
        """Move one order's visible status.

        `outlet_id`, when given, SCOPES the lookup — the order must belong to
        that outlet or this raises 404. It is keyword-only and optional because
        the internal callers (auto_receive, the release path, the roster
        processor) already hold an order they resolved themselves and are not
        acting on behalf of a request; only the staff-facing endpoint needs the
        check, and it passes it.

        Why it exists: POST /customer/orders/{id}/advance took
        `_staff=Depends(get_current_staff)` and never read the result, and the
        query below filtered on the order id alone. Any authenticated staff
        account at ANY outlet could therefore drive ANY order's status —
        including marking another restaurant's order READY, which fires the
        customer's "come and get it" push.

        404 rather than 403 for a cross-outlet id, matching lookup-pickup:
        telling a caller that an order exists but belongs to someone else
        leaks the existence of other outlets' orders.
        """
        conditions = [CustomerOrder.id == order_id]
        if outlet_id is not None:
            conditions.append(CustomerOrder.outlet_id == outlet_id)
        res = await db.execute(select(CustomerOrder).where(*conditions))
        order = res.scalars().first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # PAY AT PICKUP: NO KITCHEN WITHOUT AN ACCEPT (migration 034).
        #
        # This function maps CREATED straight to RECEIVED (see below) and, with
        # an EXPLICIT target, validates only that the target is a known stage —
        # it has never looked at the order's current status. For a prepaid order
        # that is harmless: payment is what makes it real, and an unpaid order
        # never reaches staff. A pay-at-pickup order is unpaid for its whole
        # life until the counter, so without this guard the Accept step is
        # simply skippable, and skipping it is not a cosmetic shortcut:
        #
        #   * the pickup code is minted AT ACCEPT, so the order would reach
        #     READY with no code — and /collect compares against it, so the
        #     order could never be collected or paid. Three attempts would
        #     then lock it permanently.
        #   * the stock hold is COMMITTED at accept, so the units would stay
        #     HELD and sweep_expired would reclaim them mid-cook.
        #   * acceptance_state would stay AWAITING while the order cooked, and
        #     the deadline sweeper would then cancel food already being made.
        #
        # testing_dashboard already learned half of this the hard way and
        # removed CREATED from its _APPROVABLE_STATUSES, noting there that the
        # check "has to live at this call site" because advance_status would
        # not stop it. This is that check, in the one place every caller passes
        # through rather than in each of them.
        #
        # ACCEPTED is the gate, not merely "not AWAITING": a REJECTED or
        # EXPIRED order must not advance either.
        #
        # Internal callers are unaffected. AcceptanceService.accept commits the
        # ACCEPTED transition BEFORE calling this, so its own advance passes;
        # auto_receive and the scheduled-release path only ever carry prepaid
        # orders, whose payment_mode is 'PREPAID' and which skip this entirely.
        pay_row = (await db.execute(text(
            "SELECT payment_mode, acceptance_state FROM customer_orders "
            "WHERE id = :id"), {"id": str(order_id)})).first()
        # Applies to BOTH non-gateway modes (035). A direct-UPI order has the
        # same shape of hazard: its pickup code and its payment record are both
        # written at accept, so advancing without one leaves an order that is
        # cooking, uncollectable and unpaid.
        if (pay_row is not None and (pay_row[0] or "") in _NON_GATEWAY_METHODS
                and (pay_row[1] or "") != "ACCEPTED"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "NOT_ACCEPTED",
                    "acceptance_state": pay_row[1],
                    "message": (
                        "Call the customer and accept this order before "
                        "sending it to the kitchen."
                        if (pay_row[0] or "") == PAY_AT_PICKUP else
                        "Check that the payment has arrived and accept this "
                        "order before sending it to the kitchen."
                    ),
                },
            )

        if target:
            new_status = target.upper()
            if new_status not in _PROGRESSION:
                raise HTTPException(status_code=400, detail="Invalid target status")
        else:
            cur = order.status.upper()
            if cur in ("CREATED", "PAID"):
                new_status = "RECEIVED"
            elif cur in _PROGRESSION:
                idx = _PROGRESSION.index(cur)
                new_status = _PROGRESSION[min(idx + 1, len(_PROGRESSION) - 1)]
            else:
                new_status = "RECEIVED"

        order.status = new_status
        order.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(order)
        await CarevoService._broadcast_status(order, db)

        # Roster-scoped auto-pickup (testing_dashboard, migration 025). When a
        # TESTER's order reaches READY, complete it automatically via the SAME
        # verify_pickup path staff use — reused verbatim, not reimplemented.
        # Orders from non-roster phones are untouched: the roster check inside
        # maybe_auto_pickup gates everything, and it is best-effort so it can
        # never break a real status transition. Lazy import breaks the cycle
        # (testing_dashboard imports CarevoService).
        if new_status == "READY":
            from app.modules.testing_dashboard.service import TestingService
            if await TestingService.maybe_auto_pickup(db, order):
                await db.refresh(order)  # now COMPLETED
        return order

    @staticmethod
    async def _broadcast_status(order: CustomerOrder, db: AsyncSession = None) -> None:
        """Reuse the in-memory WS layer to push Skip status changes.

        Also the single hook for FCM order-status pushes (migration 014): every
        transition already funnels through here, so notifications reuse this
        choke point instead of re-deriving which statuses changed. Wrapped so a
        push failure can never affect the order.
        """
        payload = {
            "event": "SKIP_ORDER_STATUS",
            "order_id": str(order.id),
            "order_status": order.status,
            "payment_status": order.payment_status,
            "pickup_code": order.pickup_code,
        }
        try:
            await customer_manager.send_order_update(str(order.id), payload)
        except Exception:
            pass
        try:
            await pos_manager.broadcast_to_outlet(str(order.outlet_id), payload)
        except Exception:
            pass

        # FCM push for the same transition. Best-effort and fully swallowed:
        # a notification must never fail or roll back the order it describes.
        # Inert (logged as 'skipped') until PUSH_ENABLED + a service account
        # are configured, so this is safe to ship before credentials exist.
        if db is not None:
            try:
                from app.modules.push.service import PushService
                await PushService.notify_order_status(db, order)
            except Exception:
                pass

    # ------------------------------ POS ------------------------------------
    # --------------------------- pickup miss limit -------------------------
    # The per-order 3-strike lockout only counts attempts against an order the
    # caller already resolved. A miss resolves nothing, so before this it cost
    # the caller nothing at all and could be repeated without limit — the code
    # space is 8^6, small enough that unmetered guessing is worth denying.
    @staticmethod
    def check_pickup_miss_limit(outlet_id) -> None:
        """Refuse further pickup-code attempts for an outlet that keeps missing.

        Raises 429 with a Retry-After hint rather than failing quietly, so the
        app can tell staff to wait instead of showing "not found" for a code
        that was never actually looked up.
        """
        now = time.time()
        window = float(settings.PICKUP_MISS_WINDOW_SECONDS)
        key = str(outlet_id)
        hits = [t for t in _pickup_miss_hits[key] if now - t < window]
        _pickup_miss_hits[key] = hits
        if len(hits) >= settings.PICKUP_MISS_LIMIT:
            # Until the OLDEST hit falls out of the window — that is the moment
            # a slot frees up, so it is what the client should wait for.
            retry_after = max(1, int(window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "too_many_pickup_attempts",
                    "message": (
                        "Too many incorrect pickup codes. "
                        f"Try again in about {retry_after} seconds."
                    ),
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    @staticmethod
    def record_pickup_miss(outlet_id) -> None:
        """Count one miss. Called only where nothing resolved."""
        key = str(outlet_id)
        _pickup_miss_hits[key].append(time.time())

    @staticmethod
    def clear_pickup_misses(outlet_id) -> None:
        """A hit clears the outlet's misses — the limit is on CONSECUTIVE ones.

        Real staff mistype, and a counter serving a queue should not be locked
        out by scattered typos spread across successful handovers.
        """
        _pickup_miss_hits.pop(str(outlet_id), None)

    @staticmethod
    async def verify_pickup(
        db: AsyncSession,
        order_id: uuid.UUID,
        pickup_code: str,
        outlet_id: uuid.UUID,
    ) -> dict:
        """Confirm a pickup code and close the order.

        `outlet_id` is the CALLER's outlet and is required. Without it this
        route took an order_id from the request body and looked it up
        unscoped, so any authenticated staff account could complete any
        order in the system — including another restaurant's. It now 404s
        exactly like mark_order_paid_by_staff does, and the 404 is
        deliberately indistinguishable from "no such order": a caller must
        not be able to probe which ids exist outside their own outlet.
        """
        # Checked BEFORE any work: once an outlet is over its miss budget the
        # request must not touch the database at all.
        CarevoService.check_pickup_miss_limit(outlet_id)

        # Expire this order first if its pickup window lapsed, so a stale code
        # can't be verified (and doesn't cost the staff a failed attempt).
        await CarevoService._expire_stale_pickups(db, order_id=order_id)

        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order or str(order.outlet_id) != str(outlet_id):
            # Nothing resolved, so the per-order counter cannot see this. Count
            # it here instead — this is the branch that used to be free, and
            # the one an id-enumerating caller lives in.
            CarevoService.record_pickup_miss(outlet_id)
            raise HTTPException(status_code=404, detail="Order not found for this outlet")

        if order.is_locked:
            raise HTTPException(status_code=423, detail={"verified": False, "locked": True})

        if order.status.upper() == "ABANDONED":
            return {
                "verified": False,
                "order_id": order.id,
                "status": "ABANDONED",
            }

        # PAY-AT-PICKUP MONEY GUARD (migration 034).
        #
        # THIS IS A DELIBERATE BREAKING CHANGE, and it is breaking in the only
        # direction that is safe.
        #
        # Everything below this point decides completion on the CODE and the
        # STATUS and has never once looked at payment_status — which was
        # correct while every order reaching here had been charged by a gateway
        # before the kitchen ever saw it. A pay-at-pickup order is different:
        # it is genuinely live, genuinely READY, and genuinely unpaid until
        # somebody takes the money at the counter. Left alone, this endpoint
        # would mark it COMPLETED with payment_status='PENDING' — free food,
        # recorded as a successful handover.
        #
        # So an unpaid pay-at-pickup order is refused here and must go through
        # POST /pos/orders/{id}/collect instead, which takes the money and
        # closes the order in one transaction. A DEPLOYED owner_app build that
        # calls this endpoint on such an order therefore gets a 409 it does not
        # expect — which is the point: the alternative is giving the food away,
        # and the breakage is confined to orders that can only exist at an
        # outlet an admin deliberately switched on.
        #
        # An ALREADY-PAID pay-at-pickup order falls through untouched, so a
        # second verify tap after a successful collect behaves exactly like any
        # other repeat verify.
        pay_mode = await db.scalar(text(
            "SELECT payment_mode FROM customer_orders WHERE id = :id"),
            {"id": str(order_id)})
        # Applies to BOTH non-gateway modes (035). A PAID direct-UPI order —
        # which is every one that was accepted, since accept records the
        # payment — falls straight through and completes here through the
        # ORDINARY verify-pickup path, exactly like a prepaid order. Only an
        # unpaid one is refused, and for a direct-UPI order that means it was
        # never accepted.
        if ((pay_mode or "") in _NON_GATEWAY_METHODS
                and (order.payment_status or "").upper() != "PAID"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "PAYMENT_NOT_RECORDED",
                    "order_id": str(order.id),
                    "message": (
                        "Take payment first — use \"Paid and handed over\" to "
                        "record cash or UPI and close this order."
                        if (pay_mode or "") == PAY_AT_PICKUP else
                        "This order has not been accepted yet. Check that the "
                        "payment arrived and accept it first."
                    ),
                },
            )

        code_ok = bool(order.pickup_code) and order.pickup_code.upper() == pickup_code.strip().upper()
        status_ok = order.status.upper() in _LIVE_STATUSES

        if code_ok and status_ok:
            # Resolved and confirmed — this outlet is plainly not guessing.
            CarevoService.clear_pickup_misses(outlet_id)
            order.status = "COMPLETED"
            order.pickup_verified_at = datetime.now(timezone.utc)
            order.updated_at = datetime.now(timezone.utc)
            # FR-E1: PICKUP_VERIFIED in the same transaction as COMPLETED.
            await pe.write_event(
                db, order.id, pe.PICKUP_VERIFIED,
                actor_type="staff", source="tap", outlet_id=order.outlet_id,
            )
            await db.commit()
            await db.refresh(order)
            await CarevoService._broadcast_status(order, db)
            # PE Step 4: score the terminal order (trust + outcome), best-effort.
            try:
                from app.modules.prediction.service import PredictionService
                await PredictionService.compute_outcome(db, order.id)
            except Exception:
                await db.rollback()
            return {"verified": True, "order_id": order.id, "status": "COMPLETED"}

        # Wrong code (or non-live status) — count as a failed attempt.
        order.failed_attempts = (order.failed_attempts or 0) + 1
        locked = False
        if order.failed_attempts >= 3:
            order.is_locked = True
            locked = True
        order.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(order)
        attempts_remaining = max(0, 3 - order.failed_attempts)
        return {"verified": False, "attempts_remaining": attempts_remaining, "locked": locked}

    # ---------- Direct UPI: the restaurant's way out of an expiry ----------
    #: How long after cancellation a restaurant may still report that an
    #: expired claim's money never arrived.
    #:
    #: Bounded because the claim is unverifiable after the fact and the strike
    #: lands on a CUSTOMER. A week is long enough for a restaurant to notice a
    #: missing payment while reconciling, and short enough that nobody is
    #: struck for an order they placed last month and have forgotten.
    NOT_RECEIVED_WINDOW = timedelta(days=7)

    @staticmethod
    async def report_payment_not_received(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, actor_user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """The restaurant says an EXPIRED claim's money never arrived.

        THE PROBLEM THIS SOLVES. When a direct-UPI claim expires unanswered,
        the order is cancelled with manual_refund_due = true — deliberately,
        because nobody looked and an honest customer whose money really left
        their account must not be stranded. But that leaves the restaurant
        holding a refund obligation for a payment it has no evidence of, with
        no way to say so. This is that way.
        """
        row = (await db.execute(text("""
            SELECT status, payment_mode, payment_status, manual_refund_due,
                   manual_refund_reason, customer_id, updated_at,
                   total_amount
              FROM customer_orders
             WHERE id = :id AND outlet_id = :oid
        """), {"id": str(order_id), "oid": str(outlet_id)})).first()
        # 404 for a cross-outlet id, matching every other staff route here:
        # "exists but is not yours" is information about another restaurant.
        if row is None:
            raise HTTPException(
                status_code=404, detail="Order not found for this outlet")

        # IDEMPOTENT. A second tap finds the reason already rewritten and
        # returns the same answer without striking again — which matters more
        # than usual here, because the side effect is a penalty on a customer.
        if (row.manual_refund_reason or "") == "restaurant_reported_not_received":
            return {
                "order_id": order_id,
                "manual_refund_due": bool(row.manual_refund_due),
                "already": True,
            }

        if (row.payment_mode or "") != PAY_UPI_MANUAL:
            raise HTTPException(
                status_code=404, detail="Order not found for this outlet")

        # Checked BEFORE the expiry test so the refusal names the real cause.
        # An accepted order fails both — it is not an expired claim either —
        # but "you already confirmed this payment" tells the staff member what
        # they did, where "this only applies to an expired order" leaves them
        # looking for an expiry that is not the problem. Same ordering reason
        # as CASHFREE_LOCKED ahead of the at-least-one-method rule.
        #
        # Accepting a direct-UPI order IS the payment confirmation: a human
        # read their own UPI app and said the amount was there. Reporting it
        # missing afterwards would unwind a payment this restaurant recorded
        # and strike the customer for it.
        if (row.payment_status or "").upper() == "PAID":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "PAYMENT_ALREADY_RECORDED",
                    "message": (
                        "You confirmed this payment when you accepted the "
                        "order, so it cannot be reported as missing."
                    ),
                },
            )

        # ONLY the expiry case. A cannot_make cancellation is the restaurant
        # saying the money WAS there, so letting it be reversed here would let
        # one tap undo a refund the restaurant already owes — and strike the
        # customer for the restaurant's own change of mind.
        if ((row.manual_refund_reason or "")
                != "acceptance_expired_after_payment_claim"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "NOT_AN_EXPIRED_CLAIM",
                    "message": (
                        "This only applies to an order that expired before you "
                        "confirmed the payment."
                    ),
                },
            )

        within = await db.scalar(text(
            "SELECT updated_at > now() - CAST(:w AS interval) "
            "FROM customer_orders WHERE id = :id"),
            {"w": CarevoService.NOT_RECEIVED_WINDOW, "id": str(order_id)})
        if not within:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "REPORT_WINDOW_EXPIRED",
                    "message": (
                        "This order is too old to report. Contact support if "
                        "you still need to resolve it."
                    ),
                },
            )

        # THE COMPARE-AND-SET, on the reason itself. Two taps arriving together
        # both pass the checks above; exactly one changes the row, so exactly
        # one strike is recorded.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET manual_refund_due = false,
                   manual_refund_reason = 'restaurant_reported_not_received',
                   updated_at = now()
             WHERE id = :id
               AND manual_refund_reason = 'acceptance_expired_after_payment_claim'
        """), {"id": str(order_id)})
        if res.rowcount != 1:
            await db.rollback()
            return {"order_id": order_id, "manual_refund_due": False,
                    "already": True}

        await db.execute(text(
            "UPDATE customers SET false_claim_count = false_claim_count + 1 "
            "WHERE id = :cid"), {"cid": str(row.customer_id)})

        await pe.write_event(
            db, order_id, pe.PAYMENT_NOT_RECEIVED,
            actor_type="staff", source="tap", outlet_id=outlet_id,
            actor_id=actor_user_id,
            payload={"reason": "reported_after_expiry",
                     "amount": float(row.total_amount or 0)},
        )
        await db.commit()
        return {"order_id": order_id, "manual_refund_due": False,
                "already": False}

    # ------------- Owner self-serve payment settings (035) ------------------
    #: Shape check mirroring ck_outlets_upi_vpa_shape EXACTLY, so a bad VPA is
    #: a 422 with a sentence rather than an IntegrityError or — worse — a
    #: DBAPIError from the constraint's own regex.
    #:
    #: {2,255} because PostgreSQL caps bounded repetition at 255; the two
    #: patterns must agree or one of them becomes the real rule by accident.
    _VPA_RE = re.compile(r"^[A-Za-z0-9._-]{2,255}@[A-Za-z]{2,64}$")

    @staticmethod
    async def get_owner_payment_methods(
        db: AsyncSession, outlet_id: uuid.UUID
    ) -> dict:
        """What this outlet accepts, and what it is ALLOWED to accept.

        `cashfree_unlocked` is returned so the owner app can render the Cashfree
        toggle as locked-with-a-reason instead of a switch that flips back —
        the difference between "you turned this off" and "we have not enabled
        this for you" is the whole point of the column.

        `upi_attested` is derived rather than exposing the timestamp alone, so
        the client has a boolean to bind a checkbox to.
        """
        row = (await db.execute(text("""
            SELECT payment_prepaid_enabled, payment_pay_at_pickup_enabled,
                   payment_upi_manual_enabled, cashfree_unlocked,
                   upi_vpa, upi_payee_name, upi_attested_at,
                   payment_settings_updated_at
              FROM outlets WHERE id = :oid
        """), {"oid": str(outlet_id)})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Outlet not found")
        return {
            "outlet_id": outlet_id,
            "prepaid": bool(row[0]),
            "pay_at_pickup": bool(row[1]),
            "upi_manual": bool(row[2]),
            "cashfree_unlocked": bool(row[3]),
            "upi_vpa": row[4],
            "upi_payee_name": row[5],
            "upi_attested": row[6] is not None,
            "updated_at": row[7],
            "cashfree_only": settings.CASHFREE_ONLY,
            "effective_methods": await CarevoService.payment_methods_for(
                db, outlet_id),
        }

    @staticmethod
    async def set_owner_payment_methods(
        db: AsyncSession, outlet_id: uuid.UUID, payload, *, actor_user_id
    ) -> dict:
        """The owner changes how their restaurant takes money.

        Takes the FULL state rather than a delta, same as the admin route: a
        partial update reads as harmless but is how an outlet ends up with
        nothing enabled, and stating all three makes the end state explicit in
        the request.

        FOUR RULES, and each refuses rather than silently correcting, because
        every one of them is about money reaching the right place:

        1. AT LEAST ONE METHOD (422). An outlet accepting nothing can take no
           orders. The DB CHECK refuses it too; this is what produces a
           sentence instead of an IntegrityError.

        2. PREPAID NEEDS THE PLATFORM UNLOCK (409). The owner's flag is a
           preference, cashfree_unlocked is permission, and permission is not
           the owner's to grant. The message names the state rather than the
           mechanism — an owner does not need to know the column exists.

        3. UPI NEEDS A VPA, A PAYEE NAME AND AN ATTESTATION. The attestation is
           the only test that proves anything: a regex cannot tell you whether
           a VPA reaches the person who typed it, but "I sent myself Rs 1
           through this exact ID and received it" can.

        4. CHANGING THE VPA CLEARS THE ATTESTATION AND TURNS THE METHOD OFF.
           The old attestation was about the old string. Carrying it over would
           let a one-character typo inherit the proof for a different account —
           and a direct-UPI order against a wrong VPA sends a customer's money
           to a stranger, with CareVo not in the path to claw it back. This is
           the rule most worth being strict about, and it is why re-attesting
           is a deliberate act rather than an implicit one.
        """
        current = await CarevoService.get_owner_payment_methods(db, outlet_id)

        prepaid = bool(payload.prepaid)
        pickup = bool(payload.pay_at_pickup)
        upi = bool(payload.upi_manual)

        # CASHFREE_ONLY (config.py): pay-at-pickup and direct UPI are off
        # platform-wide, not a per-outlet preference, so trying to turn
        # either on is refused as a permission problem (403) rather than a
        # validation problem (422/409) — the owner did nothing wrong, the
        # platform just isn't offering it right now. Checked first, before
        # any of the four rules below, so the refusal names the real cause.
        if settings.CASHFREE_ONLY and (pickup or upi):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "CASHFREE_ONLY_MODE",
                    "message": (
                        "Pay at pickup and UPI are switched off platform-wide "
                        "while Cashfree-only mode is active. Online payment "
                        "is the only method available."
                    ),
                },
            )

        # Rule 2, checked before the "at least one" rule so the refusal names
        # the real cause: an owner who asked for prepaid-only on a locked
        # outlet is told Cashfree is unavailable, not that they picked nothing.
        if prepaid and not current["cashfree_unlocked"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "CASHFREE_LOCKED",
                    "message": (
                        "Cashfree is currently unavailable for your restaurant."
                    ),
                },
            )

        # FIELDS-SET SEMANTICS (review fix). OMITTED MEANS UNCHANGED.
        #
        # This read `payload.upi_vpa or None`, which cannot tell "the caller
        # did not mention it" from "the caller sent null" — both arrive as
        # None. So a PATCH carrying only the three toggles wrote NULL over a
        # saved VPA and payee name, and ck_outlets_upi_manual_requires_vpa then
        # forced direct UPI off: one partial request silently destroyed the
        # restaurant's payment details and stopped it taking UPI orders.
        #
        # model_fields_set is Pydantic's record of what was actually present in
        # the request body, which is the only thing that distinguishes them.
        sent = payload.model_fields_set
        vpa_sent = "upi_vpa" in sent
        payee_sent = "upi_payee_name" in sent

        # An EXPLICIT null is refused rather than treated as a clear. There is
        # no "remove my UPI ID" operation here, and a caller sending one is
        # almost certainly building a body from a partially-populated form.
        # Turning the method off is the supported way to stop using it, and it
        # keeps the details for next time.
        if vpa_sent and payload.upi_vpa is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "UPI_ID_CANNOT_BE_CLEARED",
                    "message": (
                        "To stop taking UPI payments, turn the option off. "
                        "Your UPI ID is kept for next time."
                    ),
                },
            )
        if payee_sent and payload.upi_payee_name is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "UPI_PAYEE_CANNOT_BE_CLEARED",
                    "message": (
                        "To stop taking UPI payments, turn the option off. "
                        "Your account name is kept for next time."
                    ),
                },
            )

        # An empty STRING is still treated as "no value" — that is a cleared
        # form field, which the owner app does send, and it is not the same as
        # an explicit JSON null.
        vpa = ((payload.upi_vpa or "").strip() or None) if vpa_sent \
            else current["upi_vpa"]
        payee = ((payload.upi_payee_name or "").strip() or None) if payee_sent \
            else current["upi_payee_name"]
        attested_now = bool(getattr(payload, "upi_attested", False))

        if vpa is not None and not CarevoService._VPA_RE.match(vpa):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "INVALID_UPI_ID",
                    "message": (
                        "That does not look like a UPI ID. It should look like "
                        "name@bank."
                    ),
                },
            )

        # Rule 4. Whether the STRING changed decides whether the old proof
        # survives — not whether the client sent the checkbox.
        vpa_changed = (vpa or "") != (current["upi_vpa"] or "")
        if vpa_changed:
            attested_at_sql = "NULL"
            # The old attestation is void, so the method cannot stay on unless
            # this same request re-attests the new string.
            still_attested = attested_now
        else:
            still_attested = current["upi_attested"] or attested_now
            attested_at_sql = "now()" if (attested_now and
                                          not current["upi_attested"]) else \
                "upi_attested_at"

        # Rule 3.
        if upi:
            if not vpa or not payee:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "UPI_DETAILS_REQUIRED",
                        "message": (
                            "Add your UPI ID and the name on the account "
                            "before turning this on."
                        ),
                    },
                )
            if not still_attested:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "UPI_ATTESTATION_REQUIRED",
                        "message": (
                            "Send yourself Rs 1 using this UPI ID, confirm you "
                            "received it, then turn this on."
                        ),
                    },
                )
            attested_at_sql = "now()" if vpa_changed or not current["upi_attested"] \
                else "upi_attested_at"
        elif vpa_changed:
            # VPA changed while the method is off: keep the new string, drop any
            # stale proof. Re-attestation is then required to turn it on.
            attested_at_sql = "NULL"

        # Rule 1, last: by here the other three have had their say, so a
        # both-off refusal is genuinely about picking nothing.
        if not (prepaid or pickup or upi):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "NO_PAYMENT_METHOD",
                    "message": (
                        "Your restaurant must accept at least one payment "
                        "method. Turn on online payment, pay at pickup, or UPI."
                    ),
                },
            )

        # THE FLAGS CAN ALL BE "ON" AND THE OUTLET STILL TAKE NOTHING.
        #
        # ck_outlets_payment_method_any only requires one FLAG to be true, and
        # prepaid additionally needs the platform unlock and a live gateway. So
        # (prepaid=true, pay_at_pickup=false, upi=false, cashfree_unlocked=
        # false) satisfies the constraint, satisfies the "at least one" rule
        # below, and resolves to an EMPTY method list — an outlet that cannot
        # be ordered from, saved without a word of warning.
        #
        # Checked against the resolver itself rather than by re-deriving the
        # rule, so the two can never disagree.
        if not await CarevoService._would_offer_anything(
                db, outlet_id, prepaid=prepaid, pickup=pickup, upi=upi):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "NO_EFFECTIVE_PAYMENT_METHOD",
                    "message": (
                        "These settings would leave customers unable to order. "
                        "Online payment is not active for your restaurant yet, "
                        "so turn on pay at pickup or UPI."
                    ),
                },
            )

        row = (await db.execute(text(f"""
            UPDATE outlets
               SET payment_prepaid_enabled = :prepaid,
                   payment_pay_at_pickup_enabled = :pickup,
                   payment_upi_manual_enabled = :upi,
                   upi_vpa = :vpa,
                   upi_payee_name = :payee,
                   upi_attested_at = {attested_at_sql},
                   payment_settings_updated_at = now(),
                   payment_settings_updated_by = :actor
             WHERE id = :oid
            RETURNING id
        """), {"prepaid": prepaid, "pickup": pickup, "upi": upi,
               "vpa": vpa, "payee": payee,
               "actor": str(actor_user_id) if actor_user_id else None,
               "oid": str(outlet_id)})).first()
        if row is None:
            await db.rollback()
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()

        return await CarevoService.get_owner_payment_methods(db, outlet_id)

    # --------------------- Direct UPI: the claim (035) ----------------------
    @staticmethod
    async def claim_upi_payment(
        db: AsyncSession, order_id: uuid.UUID, customer: Customer
    ) -> dict:
        """The customer says they have sent the money. Starts the clock.

        THIS DOES NOT CONFIRM A PAYMENT and the naming is deliberate
        throughout: `payment_claimed_at`, not `paid_at`. All it records is that
        one party asserted something. payment_status stays PENDING until a
        human at the restaurant looks at their own UPI app and taps Accept,
        which is the only evidence that exists.

        What it DOES do is three things that must happen together:

          * stamps payment_claimed_at, which is what makes Accept available;
          * COMMITS the stock hold, because from here the order is going to
            the restaurant to be judged and its units must stop being
            sweepable mid-decision;
          * opens the acceptance window, so a restaurant that never looks
            cannot leave the customer waiting forever — the order expires and
            is flagged for a manual refund, since by then the money may really
            have been sent.

        SCOPED TO THE ORDER'S OWN CUSTOMER. get_order already enforces that,
        and it is reused rather than re-implemented.

        IDEMPOTENT by compare-and-set on payment_claimed_at IS NULL, so a
        double-tap on a slow connection returns the first claim rather than
        re-committing stock or restarting the clock.
        """
        order = await CarevoService.get_order(db, order_id, customer)

        mode = await db.scalar(text(
            "SELECT payment_mode FROM customer_orders WHERE id = :id"),
            {"id": str(order_id)})
        if (mode or "") != PAY_UPI_MANUAL:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "NOT_A_UPI_ORDER",
                    "message": "This order is not paid by UPI.",
                })

        existing = await db.scalar(text(
            "SELECT payment_claimed_at FROM customer_orders WHERE id = :id"),
            {"id": str(order_id)})
        if existing is not None:
            # Already claimed. Not an error — the second tap of a double-tap.
            return {
                "order_id": order_id,
                "claimed": True,
                "already": True,
                "payment_claimed_at": existing,
                "status": order.status,
            }

        current = (order.status or "").upper()
        if current != "CREATED":
            # Past CREATED the order has either been dealt with or expired;
            # either way there is nothing left to claim against.
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "NOT_CLAIMABLE",
                    "status": order.status,
                    "message": (
                        f"This order is {order.status} and can no longer be "
                        "marked as paid."
                    ),
                })

        # THE PAY WINDOW. Past it the order is already cancellable by the
        # sweep, and accepting a claim now would be accepting one against an
        # order whose stock has been given back.
        #
        # Compared in SQL against the row's own created_at rather than in
        # Python, so there is no client clock and no timezone in the decision.
        within = await db.scalar(text(
            "SELECT created_at > now() - make_interval(secs => :w) "
            "FROM customer_orders WHERE id = :id"),
            {"w": UPI_PAY_WINDOW_SECONDS, "id": str(order_id)})
        if not within:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "PAY_WINDOW_EXPIRED",
                    "message": (
                        "This order has expired. Place it again and pay within "
                        "a few minutes."
                    ),
                })

        # COMPARE-AND-SET on payment_claimed_at IS NULL — the winner-picker for
        # two taps arriving together.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET payment_claimed_at = now(), updated_at = now()
             WHERE id = :id AND payment_claimed_at IS NULL
               AND upper(coalesce(status, '')) = 'CREATED'
        """), {"id": str(order_id)})
        if res.rowcount != 1:
            await db.rollback()
            claimed = await db.scalar(text(
                "SELECT payment_claimed_at FROM customer_orders WHERE id = :id"),
                {"id": str(order_id)})
            return {"order_id": order_id, "claimed": claimed is not None,
                    "already": True, "payment_claimed_at": claimed,
                    "status": order.status}

        # The units are now committed to this order while the restaurant
        # decides. Same reasoning as accept for pay-at-pickup: an order under
        # human judgement must not have its stock reclaimed underneath it.
        from app.modules.carevo_customer.stock import StockService
        await StockService.commit_for_order(db, order_id)

        # The acceptance window opens HERE, not at placement.
        from app.modules.carevo_customer.acceptance import AcceptanceService
        await AcceptanceService.begin_awaiting(db, order, reason="upi_claimed")

        await pe.write_event(
            db, order_id, pe.PAYMENT_CLAIMED,
            actor_type="customer", actor_id=customer.id, source="tap",
            outlet_id=order.outlet_id,
            payload={"amount": float(order.total_amount or 0),
                     "note": CarevoService.short_order_number(order_id)},
        )
        await db.commit()

        # Rung 1 of the alert ladder, after the commit and best-effort — same
        # contract as every other entry into AWAITING.
        await AcceptanceService.send_first_alert(db, order)

        claimed_at = await db.scalar(text(
            "SELECT payment_claimed_at FROM customer_orders WHERE id = :id"),
            {"id": str(order_id)})
        return {
            "order_id": order_id,
            "claimed": True,
            "already": False,
            "payment_claimed_at": claimed_at,
            "status": order.status,
        }

    # ------------------- Pay at pickup: staff actions (034) -----------------
    @staticmethod
    async def _pickup_order_or_404(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID
    ):
        """One PAY-AT-PICKUP order at THIS outlet, or 404.

        404 rather than 403 for a cross-outlet id, and 404 rather than 409 for
        a prepaid one — both for the reason lookup_pickup already documents:
        "exists but is not yours" and "exists but is not that kind" are both
        information about orders the caller has no business knowing about.
        """
        # CONTACT COLUMNS ARE DELIBERATELY NOT SELECTED.
        #
        # None of the three callers (log_call, collect_order, mark_no_show)
        # returns them, so selecting them only put the customer's phone number
        # into three code paths that have no use for it — one stray `return
        # row` away from a leak. The owner QUEUE is the single place a contact
        # is read, and it applies the visibility window in SQL.
        row = (await db.execute(text("""
            SELECT id, status, payment_status, payment_mode, call_state,
                   call_attempts, total_amount, customer_id, pickup_code
              FROM customer_orders
             WHERE id = :id AND outlet_id = :oid AND payment_mode = :mode
        """), {"id": str(order_id), "oid": str(outlet_id),
               "mode": PAY_AT_PICKUP})).first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Order not found for this outlet")
        return row

    @staticmethod
    async def log_call(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, actor_user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Record that staff rang the customer. Does NOT decide the order.

        Deliberately separate from accept/reject, and deliberately does not
        touch the deadline. The call is evidence that somebody is working the
        order; it is not a decision, and letting it extend the window would
        make "ring and do nothing" a way to park an order indefinitely while
        the customer waits — the same trap alert-ack was designed to avoid.

        Idempotent in the sense that matters: calling twice is a real thing
        that happens (no answer the first time), so it counts up rather than
        refusing. first_call_at keeps the FIRST attempt, so "how long before
        anyone rang" stays answerable after a second attempt overwrites
        nothing.
        """
        row = await CarevoService._pickup_order_or_404(db, order_id, outlet_id)

        if (row.status or "").upper() in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"This order is {row.status} — there is nothing to confirm.")

        res = await db.execute(text("""
            UPDATE customer_orders
               SET call_state = 'CALLED',
                   call_attempts = call_attempts + 1,
                   first_call_at = COALESCE(first_call_at, now())
             WHERE id = :id AND payment_mode = :mode
            RETURNING call_attempts, first_call_at
        """), {"id": str(order_id), "mode": PAY_AT_PICKUP})
        updated = res.first()
        attempts = int(updated[0]) if updated else 1

        await pe.write_event(
            db, order_id, pe.ORDER_CALL_PLACED,
            actor_type="staff", source="tap", outlet_id=outlet_id,
            actor_id=actor_user_id,
            payload={"attempt": attempts},
        )
        await db.commit()
        return {
            "order_id": order_id,
            "call_state": "CALLED",
            "call_attempts": attempts,
        }

    @staticmethod
    async def record_pickup_payment(
        db: AsyncSession, order, *, method: str,
        actor_user_id: Optional[uuid.UUID] = None,
        at_counter: bool = True,
    ) -> None:
        """Record money a human confirmed arrived OUTSIDE the gateway.

        Two callers, both of them "a staff member looked and the money is
        there", which is why this is one function and not two:

          * the pay-at-pickup counter handover (at_counter=True) — cash or UPI
            handed over in person as the food is collected;
          * the direct-UPI accept (at_counter=False, migration 035) — the
            restaurant checked its own UPI app before agreeing to cook.

        `at_counter` only rides the event payload. It changes nothing about
        what is written, and exists so "was this money taken face to face"
        stays answerable from the log — the two cases are a different kind of
        risk and will eventually want different reporting.

        Runs in the CALLER's transaction.

        DOES NOT COMMIT and does not touch `status` — both are the caller's
        job, because this has to land atomically with the COMPLETED transition.

        WHY NOT mark_paid. mark_paid is the gateway's entry point and does two
        things that are wrong here: it sets status='PAID', which would drag a
        READY order backwards, and it mints a pickup code, which this order has
        had since it was accepted. It also starts the acceptance clock and takes
        a scheduled hold, neither of which means anything at handover time. The
        overlap is the PaymentTransaction row, the ORDER_PAID event and the
        points accrual — all three of which are done here explicitly.

        ORDER_PAID is written ALONGSIDE PAYMENT_COLLECTED on purpose: every
        existing reader of "when was this order paid" keeps working, and the
        new event carries what ORDER_PAID cannot (in person, by this method, by
        this staff member).
        """
        if method not in ("cash", "upi"):
            raise HTTPException(
                status_code=422, detail="method must be 'cash' or 'upi'")

        # A transaction row so the money is in the same ledger as every gateway
        # payment. gateway='counter' names the path honestly rather than
        # borrowing a provider's name for cash in a till.
        db.add(PaymentTransaction(
            customer_order_id=order.id,
            gateway="counter" if at_counter else "upi_manual",
            amount=order.total_amount,
            currency="INR",
            status="PAID",
            method=method,
        ))

        order.payment_status = "PAID"
        order.updated_at = datetime.now(timezone.utc)

        await db.execute(text("""
            UPDATE customer_orders
               SET collected_payment_method = :m,
                   collected_at = now(),
                   collected_by = :by
             WHERE id = :id
        """), {"m": method, "by": str(actor_user_id) if actor_user_id else None,
               "id": str(order.id)})

        await pe.write_event(
            db, order.id, pe.ORDER_PAID,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            actor_id=actor_user_id,
            payload={"method": method, "at_counter": at_counter},
        )
        await pe.write_event(
            db, order.id, pe.PAYMENT_COLLECTED,
            actor_type="staff", source="tap", outlet_id=order.outlet_id,
            actor_id=actor_user_id,
            payload={"method": method, "amount": float(order.total_amount or 0),
                     "at_counter": at_counter},
        )

        # Loyalty accrual, in the SAME transaction as the payment — identical
        # discipline to mark_paid: points are earned iff the payment is
        # recorded, and the two cannot diverge through a partial failure.
        await CarevoService._accrue_points(db, order)

    @staticmethod
    async def collect_order(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, pickup_code: str, method: str,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Take the money and hand the food over. ONE transaction.

        The two halves are inseparable by design. Recording payment without
        completing the order leaves money against food still on the counter;
        completing without recording payment gives it away. Doing them in one
        transaction is why this is its own endpoint rather than a mark-paid tap
        followed by a verify-pickup tap.

        CODE-GATED exactly like the prepaid handover: the customer shows their
        code, and a wrong one neither completes the order nor records the
        money. The per-outlet miss cap and the per-order 3-strike lock both
        still apply, so this is not a weaker check than verify_pickup — it is
        the same check with payment attached.

        Compare-and-set on status, so two tablets tapping it resolve to one
        winner and the loser is told what beat it.
        """
        if method not in ("cash", "upi"):
            raise HTTPException(
                status_code=422, detail="method must be 'cash' or 'upi'")

        CarevoService.check_pickup_miss_limit(outlet_id)

        row = await CarevoService._pickup_order_or_404(db, order_id, outlet_id)

        if bool((await db.scalar(text(
                "SELECT is_locked FROM customer_orders WHERE id = :id"),
                {"id": str(order_id)}))):
            raise HTTPException(
                status_code=423, detail={"verified": False, "locked": True})

        code_ok = bool(row.pickup_code) and (
            (row.pickup_code or "").upper() == (pickup_code or "").strip().upper())

        if not code_ok:
            # Same accounting as verify_pickup, in BOTH respects.
            #
            # The per-order 3-strike lock below was already here. The
            # per-OUTLET miss cap was not: check_pickup_miss_limit was read at
            # the top of this function but nothing ever incremented it, so the
            # cap could not trip from this endpoint however many codes were
            # tried through it. verify_pickup records a miss on the branch
            # that resolves nothing; this records one on the branch that
            # resolves an order but not its code, which is the equivalent
            # here — the order id is the thing the caller supplied, so a wrong
            # code is the guess.
            CarevoService.record_pickup_miss(outlet_id)
            res = await db.execute(text("""
                UPDATE customer_orders
                   SET failed_attempts = coalesce(failed_attempts, 0) + 1,
                       is_locked = (coalesce(failed_attempts, 0) + 1) >= 3,
                       updated_at = now()
                 WHERE id = :id
                RETURNING failed_attempts, is_locked
            """), {"id": str(order_id)})
            got = res.first()
            await db.commit()
            return {
                "collected": False,
                "order_id": order_id,
                "attempts_remaining": max(0, 3 - int(got[0] or 0)) if got else 0,
                "locked": bool(got[1]) if got else False,
            }

        # Right code at this outlet — clear any run of misses before it.
        CarevoService.clear_pickup_misses(outlet_id)

        # THE COMPARE-AND-SET. Only a live, uncollected order may be collected.
        # READY is the normal case; RECEIVED/PREPARING are allowed because a
        # customer who turns up early should not be refused their own food
        # while it sits finished but unmarked.
        res = await db.execute(text("""
            UPDATE customer_orders
               SET status = 'COMPLETED',
                   pickup_verified_at = now(),
                   updated_at = now()
             WHERE id = :id
               AND upper(coalesce(status, '')) IN ('RECEIVED','PREPARING','READY')
        """), {"id": str(order_id)})
        if res.rowcount != 1:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_collectable",
                    "status": row.status,
                    "message": (
                        f"This order is {row.status} and cannot be collected."
                    ),
                },
            )

        # The ORM object, loaded only now that the row is ours — it is what
        # record_pickup_payment and _accrue_points need, and loading it before
        # winning the CAS would have been a wasted query on the losing path.
        order = (await db.execute(
            select(CustomerOrder).where(CustomerOrder.id == order_id)
        )).scalars().first()

        await CarevoService.record_pickup_payment(
            db, order, method=method, actor_user_id=actor_user_id)

        await pe.write_event(
            db, order_id, pe.PICKUP_VERIFIED,
            actor_type="staff", source="tap", outlet_id=outlet_id,
            actor_id=actor_user_id,
        )
        await db.commit()
        await db.refresh(order)

        await CarevoService._broadcast_status(order, db)
        try:
            from app.modules.prediction.service import PredictionService
            await PredictionService.compute_outcome(db, order_id)
        except Exception:
            await db.rollback()

        return {
            "collected": True,
            "order_id": order_id,
            "status": order.status,
            "payment_status": order.payment_status,
            "collected_payment_method": method,
        }

    @staticmethod
    async def mark_no_show(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        *, actor_user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """The customer never came. ABANDONED, stock back, strike recorded.

        The food was made and nobody paid for it, so this is the one terminal
        cause that costs the restaurant real money — which is why it is the one
        that increments customers.no_show_count.

        NO REFUND IS FLAGGED: nothing was ever charged. That is the whole
        reason _expire_one's refund flag had to become conditional too.

        Allowed only from READY (and PREPARING, for a kitchen that marks states
        late). Not from CREATED — an order nobody has confirmed yet is not a
        no-show, it is an unanswered order, and the call window owns that.
        """
        row = await CarevoService._pickup_order_or_404(db, order_id, outlet_id)

        current = (row.status or "").upper()
        if current not in ("PREPARING", "READY"):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "not_a_no_show",
                    "status": row.status,
                    "message": (
                        f"An order in {row.status} cannot be marked a no-show."
                    ),
                },
            )

        res = await db.execute(text("""
            UPDATE customer_orders
               SET status = 'ABANDONED',
                   no_show_at = now(),
                   updated_at = now()
             WHERE id = :id
               AND upper(coalesce(status, '')) IN ('PREPARING','READY')
        """), {"id": str(order_id)})
        if res.rowcount != 1:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"error": "not_a_no_show", "status": row.status,
                        "message": "This order was already dealt with."})

        # The strike. On `customers`, not on the order: it is a fact about a
        # person across outlets, and the cap it feeds is global for the same
        # reason the open-order cap is.
        await db.execute(text(
            "UPDATE customers SET no_show_count = no_show_count + 1 "
            "WHERE id = :cid"), {"cid": str(row.customer_id)})

        # STOCK IS NOT RETURNED. The food was cooked and then wasted, so the
        # ingredients are genuinely gone — and `stock_remaining` is the
        # customer-facing availability gate, so putting the units back would
        # offer the next customer portions the kitchen does not have.
        #
        # This reverses the earlier reading (which released committed units on
        # the grounds that a restaurant eating a loss would rather keep selling
        # the dish). Two things settled it: `release_for_order`'s own contract
        # already says "a COMMITTED reservation is never released by this — the
        # food was made", and the TTL sweeper, which is the SAME real-world
        # event arriving by clock instead of by tap, only ever released HELD
        # rows. Having the two disagree meant the dish's availability depended
        # on whether staff tapped a button, which is not a difference anybody
        # could explain. They now agree, and the `include_committed` escape
        # hatch is gone rather than left lying around.
        #
        # Nothing is released at all here: reaching this point requires
        # PREPARING/READY, which requires an accept, which COMMITTED the hold.
        # There is no HELD row left to give back.

        await pe.write_event(
            db, order_id, pe.ORDER_NO_SHOW,
            actor_type="staff", source="tap", outlet_id=outlet_id,
            actor_id=actor_user_id,
            payload={"from_status": current, "refund_required": False},
        )
        await db.commit()

        order = (await db.execute(
            select(CustomerOrder).where(CustomerOrder.id == order_id)
        )).scalars().first()
        if order is not None:
            await CarevoService._broadcast_status(order, db)

        return {"order_id": order_id, "status": "ABANDONED", "no_show": True}

    @staticmethod
    async def lookup_pickup(
        db: AsyncSession, outlet_id: uuid.UUID, pickup_code: str
    ) -> dict:
        """Find a live order at THIS outlet by its pickup code. Read-only.

        Staff type the code the customer shows them and get back the order to
        check against the bag. It deliberately does not close anything: the
        confirm tap goes on to verify_pickup, which owns the state change. A
        lookup that completed the order would mean a mistyped-but-valid code
        closed someone else's order with no chance to notice.

        No new identifier is introduced — this matches the SAME pickup_code
        already issued at payment and shown in the customer app.

        Scoping is by the caller's own outlet in the WHERE clause, so another
        outlet's code cannot match even in principle. That is also why the
        code alone is enough to find the order: it is unique among an outlet's
        live orders by construction (_generate_pickup_code), though not
        globally, so the outlet filter is what makes the lookup unambiguous
        rather than merely private.
        """
        code = (pickup_code or "").strip().upper()
        if not code:
            # Not an attempt at a code, so it is not counted as a miss — the
            # app refuses an empty box before it ever gets here.
            return {"found": False}

        # Checked BEFORE any work: once an outlet is over its miss budget the
        # request must not touch the database at all.
        CarevoService.check_pickup_miss_limit(outlet_id)

        # Same check-on-read sweep the queue does, so a code whose pickup
        # window has lapsed stops matching at the same moment the order
        # leaves the queue rather than some later request.
        await CarevoService._expire_stale_pickups(db, outlet_id=outlet_id)

        # payment_mode is SELECTed so the counter can see it owes money on this
        # order before tapping confirm; the CONTACT COLUMNS ARE NOT.
        #
        # Deliberate, and not an oversight for consistency with the queue: this
        # is a code-lookup at the counter with the customer physically present.
        # Their phone number answers no question being asked here, and a lookup
        # endpoint that returns a contact for any code typed into it is a
        # strictly worse thing to hold than one that does not — the miss cap
        # bounds guessing, it does not prevent it.
        row = (await db.execute(text("""
            SELECT id, status, payment_status, is_locked, total_amount,
                   created_at, pickup_verified_at, payment_mode,
                   collected_payment_method
            FROM customer_orders
            WHERE outlet_id = :oid
              AND upper(pickup_code) = :code
              AND status = ANY(:live)
            LIMIT 1
        """), {
            "oid": str(outlet_id),
            "code": code,
            "live": list(_LIVE_STATUSES),
        })).first()

        if not row:
            CarevoService.record_pickup_miss(outlet_id)
            return {"found": False}

        # A real code at this outlet — clear the run of misses before it.
        CarevoService.clear_pickup_misses(outlet_id)

        items = (await db.execute(text("""
            SELECT id, name_snap, quantity
            FROM customer_order_items
            WHERE customer_order_id = :id
            ORDER BY created_at
        """), {"id": str(row.id)})).fetchall()

        return {
            "found": True,
            # Surfaced so the app can show the lockout instead of a confirm
            # button it already knows the server will refuse with a 423.
            "locked": bool(row.is_locked),
            "order": {
                "order_id": row.id,
                "status": row.status,
                "payment_status": row.payment_status,
                "is_locked": bool(row.is_locked),
                "total_amount": float(row.total_amount) if row.total_amount is not None else 0.0,
                "created_at": row.created_at,
                "pickup_verified_at": row.pickup_verified_at,
                # 034: so the counter knows whether money is still owed on this
                # order before it taps confirm. No contact fields here — see
                # the query above.
                "payment_mode": row.payment_mode,
                "collected_payment_method": row.collected_payment_method,
                "items": [
                    {"id": it.id, "name": it.name_snap, "quantity": it.quantity}
                    for it in items
                ],
            },
        }

    # ------------------------- Owner App (staff) ---------------------------
    @staticmethod
    async def _load_owner_outlet(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        """Single source of the OwnerOutletOut shape, so GET and every setter
        return the SAME fields — a setter that omitted the hours would make the
        app clobber them to null when the owner merely toggled the photo."""
        row = (await db.execute(text(
            "SELECT id, location_name, is_visible, image_url, "
            "       opens_at, closes_at, is_manually_closed, latitude, longitude "
            "FROM outlets WHERE id = :oid"
        ), {"oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        avail = CarevoService.outlet_availability(
            row.opens_at, row.closes_at, bool(row.is_manually_closed))
        return {
            "id": row.id, "location_name": row.location_name,
            "is_visible": bool(row.is_visible), "image_url": row.image_url,
            "opening_time": row.opens_at.strftime("%H:%M") if row.opens_at else None,
            "closing_time": row.closes_at.strftime("%H:%M") if row.closes_at else None,
            "is_manually_closed": bool(row.is_manually_closed),
            # The owner sees the same live state a customer would (migration 024).
            "order_status": avail["status"],
            # Coordinates the customer app sorts by distance on. DECIMAL out of
            # the driver, so cast — a Decimal would not survive JSON encoding.
            "latitude": float(row.latitude) if row.latitude is not None else None,
            "longitude": float(row.longitude) if row.longitude is not None else None,
        }

    @staticmethod
    async def get_owner_outlet(db: AsyncSession, outlet_id: uuid.UUID) -> dict:
        return await CarevoService._load_owner_outlet(db, outlet_id)

    @staticmethod
    def _parse_hhmm(value: Optional[str]) -> Optional[dtime]:
        """'HH:MM' -> datetime.time, or None to clear. Validated at the schema
        edge too, but re-checked here so the service can never write garbage."""
        v = (value or "").strip()
        if not v:
            return None
        try:
            hh, mm = v.split(":")
            return dtime(hour=int(hh), minute=int(mm))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail=f"Invalid time: {value!r}")

    @staticmethod
    async def set_outlet_hours(
        db: AsyncSession, outlet_id: uuid.UUID,
        opening_time: Optional[str], closing_time: Optional[str]
    ) -> dict:
        """Set (or clear, with nulls) the daily opening/closing schedule.

        Both-or-neither is NOT enforced — a half-set schedule (only one time)
        reads as "no schedule" in outlet_availability and is harmless — but the
        app sends both together.
        """
        o = CarevoService._parse_hhmm(opening_time)
        c = CarevoService._parse_hhmm(closing_time)
        row = (await db.execute(text(
            "UPDATE outlets SET opens_at = :o, closes_at = :c WHERE id = :oid "
            "RETURNING id"
        ), {"o": o, "c": c, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        return await CarevoService._load_owner_outlet(db, outlet_id)

    @staticmethod
    async def set_outlet_manual_closed(
        db: AsyncSession, outlet_id: uuid.UUID, is_manually_closed: bool
    ) -> dict:
        """The on-demand 'temporarily closed' toggle. Independent of the
        schedule and of is_visible — see migration 024."""
        row = (await db.execute(text(
            "UPDATE outlets SET is_manually_closed = :m WHERE id = :oid "
            "RETURNING id"
        ), {"m": bool(is_manually_closed), "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        return await CarevoService._load_owner_outlet(db, outlet_id)

    @staticmethod
    async def set_outlet_location(
        db: AsyncSession, outlet_id: uuid.UUID,
        latitude: float, longitude: float,
    ) -> dict:
        """Pin the outlet's coordinates, from the owner tapping "Use current
        location" while standing in their own restaurant.

        Scoped to the caller's own outlet by the controller — there is no
        outlet_id parameter — so one owner cannot move another's pin.

        Range is validated at the schema edge AND here: a swapped lat/lng pair
        is still in range and cannot be detected, but an out-of-range value is
        a guaranteed-wrong pin and is worth refusing rather than storing. The
        columns are DECIMAL(10,8)/(11,8), so a latitude above 99 would not fit
        the column either.
        """
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            raise HTTPException(
                status_code=422,
                detail="Coordinates out of range",
            )
        row = (await db.execute(text(
            "UPDATE outlets SET latitude = :lat, longitude = :lng "
            "WHERE id = :oid RETURNING id"
        ), {"lat": latitude, "lng": longitude, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        # Full OwnerOutletOut, so the app does not lose the hours or the photo
        # when the owner only moved the pin.
        return await CarevoService._load_owner_outlet(db, outlet_id)

    @staticmethod
    async def set_outlet_image(
        db: AsyncSession, outlet_id: uuid.UUID, image_url: Optional[str]
    ) -> dict:
        """Store the outlet storefront photo URL (migration 011).

        The upload itself happens client-side against Cloudinary's unsigned
        endpoint - the same pipeline dish images already use - so the backend
        only ever stores the resulting URL and never handles image bytes.
        Passing null clears the photo, returning the card to its fallback glyph.
        """
        url = (image_url or "").strip() or None
        row = (await db.execute(text(
            "UPDATE outlets SET image_url = :u WHERE id = :oid RETURNING id"
        ), {"u": url, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        # Full OwnerOutletOut shape (incl. hours), so the app does not lose the
        # schedule when the owner only changed the photo.
        return await CarevoService._load_owner_outlet(db, outlet_id)

    @staticmethod
    async def set_outlet_visibility(
        db: AsyncSession, outlet_id: uuid.UUID, is_visible: bool
    ) -> dict:
        row = (await db.execute(text(
            "UPDATE outlets SET is_visible = :v WHERE id = :oid RETURNING id, is_visible"
        ), {"v": is_visible, "oid": str(outlet_id)})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Outlet not found")
        await db.commit()
        return {"id": row[0], "is_visible": bool(row[1])}

    # SELECT clause shared by the owner list + single-item reads, so responses
    # are shaped identically everywhere.
    _OWNER_ITEM_COLS = """
        mi.id, mi.name, mi.is_available, mi.is_active, mi.base_price,
        mi.is_veg, mi.prep_time_minutes, mi.image_url,
        -- Limited quantity (migration 033). NULL = untracked, which is every
        -- item until an owner sets a number.
        mi.stock_remaining,
        c.id AS category_id, c.name AS category_name
    """

    @staticmethod
    def _owner_item_dict(r) -> dict:
        return {
            "id": r.id,
            "name": r.name,
            "is_available": bool(r.is_available),
            "is_active": bool(r.is_active),
            "base_price": float(r.base_price) if r.base_price is not None else 0.0,
            "is_veg": bool(r.is_veg),
            "prep_time_minutes": r.prep_time_minutes,
            "image_url": r.image_url,
            "stock_remaining": r.stock_remaining,
            "category_id": r.category_id,
            "category_name": r.category_name,
        }

    @staticmethod
    async def list_owner_menu_items(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        """Flat list of the outlet's latest-menu items (no category grouping)."""
        rows = (await db.execute(text(f"""
            SELECT {CarevoService._OWNER_ITEM_COLS}
            FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :oid AND m.is_latest = true
              AND mi.is_active = true
            ORDER BY mi.name
        """), {"oid": str(outlet_id)})).fetchall()
        return [CarevoService._owner_item_dict(r) for r in rows]

    @staticmethod
    async def _owner_item_or_404(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID) -> dict:
        """Read one item scoped to the caller's outlet, or 404."""
        r = (await db.execute(text(f"""
            SELECT {CarevoService._OWNER_ITEM_COLS}
            FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE mi.id = :iid AND m.outlet_id = :oid
            LIMIT 1
        """), {"iid": str(item_id), "oid": str(outlet_id)})).first()
        if not r:
            raise HTTPException(status_code=404, detail="Menu item not found for this outlet")
        return CarevoService._owner_item_dict(r)

    @staticmethod
    async def _category_of_outlet_or_400(db: AsyncSession, category_id: uuid.UUID, outlet_id: uuid.UUID) -> None:
        """Guard: a category must belong to the caller's latest menu."""
        ok = (await db.execute(text("""
            SELECT 1 FROM categories c
            JOIN menus m ON m.id = c.menu_id
            WHERE c.id = :cid AND m.outlet_id = :oid AND m.is_latest = true
            LIMIT 1
        """), {"cid": str(category_id), "oid": str(outlet_id)})).first()
        if not ok:
            raise HTTPException(status_code=400, detail="Category not found for this outlet")

    @staticmethod
    async def list_owner_categories(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        rows = (await db.execute(text("""
            SELECT c.id, c.name FROM categories c
            JOIN menus m ON m.id = c.menu_id
            WHERE m.outlet_id = :oid AND m.is_latest = true
            ORDER BY c.name
        """), {"oid": str(outlet_id)})).fetchall()
        return [{"id": r.id, "name": r.name} for r in rows]

    @staticmethod
    async def create_menu_item(db: AsyncSession, outlet_id: uuid.UUID, payload) -> dict:
        await CarevoService._category_of_outlet_or_400(db, payload.category_id, outlet_id)
        row = (await db.execute(text("""
            INSERT INTO menu_items
                (id, category_id, name, base_price, is_veg, prep_time_minutes,
                 image_url, is_active, is_available, created_at)
            VALUES
                (gen_random_uuid(), :cid, :name, :price, :veg, :prep,
                 :img, true, true, now())
            RETURNING id
        """), {
            "cid": str(payload.category_id),
            "name": payload.name,
            "price": payload.base_price,
            "veg": payload.is_veg,
            "prep": payload.prep_time_minutes,
            "img": payload.image_url,
        })).first()
        await db.commit()
        return await CarevoService._owner_item_or_404(db, row[0], outlet_id)

    @staticmethod
    async def update_menu_item(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID, payload) -> dict:
        # Ownership guard first (404 if not the caller's item).
        await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        fields = payload.model_dump(exclude_unset=True)
        if "category_id" in fields and fields["category_id"] is not None:
            await CarevoService._category_of_outlet_or_400(db, fields["category_id"], outlet_id)
        if not fields:
            return await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        # Build a parameterized SET clause from whitelisted columns only.
        allowed = {"name", "base_price", "category_id", "is_veg",
                   "prep_time_minutes", "image_url", "is_available"}
        sets, params = [], {"iid": str(item_id)}
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = :{k}")
            params[k] = str(v) if k == "category_id" and v is not None else v
        await db.execute(text(f"UPDATE menu_items SET {', '.join(sets)} WHERE id = :iid"), params)
        await db.commit()
        return await CarevoService._owner_item_or_404(db, item_id, outlet_id)

    @staticmethod
    async def delete_menu_item(db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID) -> dict:
        # Soft delete: deactivate rather than DROP, preserving order history refs.
        await CarevoService._owner_item_or_404(db, item_id, outlet_id)
        row = (await db.execute(text(
            "UPDATE menu_items SET is_active = false, is_available = false "
            "WHERE id = :iid RETURNING id, is_active"
        ), {"iid": str(item_id)})).first()
        await db.commit()
        return {"ok": True, "id": row[0], "is_active": bool(row[1])}

    # ------------------------- Owner self-signup ---------------------------
    @staticmethod
    def check_register_rate_limit(client_ip: str) -> None:
        """Per-IP cap, mirroring check_otp_rate_limit (single-process; Redis in prod)."""
        now = time.time()
        window = 3600.0
        hits = [t for t in _register_hits[client_ip] if now - t < window]
        if len(hits) >= settings.REGISTER_RATE_LIMIT_PER_HOUR:
            _register_hits[client_ip] = hits
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many registration attempts, try later",
            )
        hits.append(now)
        _register_hits[client_ip] = hits

    @staticmethod
    async def register_owner(db: AsyncSession, payload, client_ip: str) -> dict:
        """Public owner self-signup. Bootstraps organization + outlet
        (pending_verification, hidden) + owner user + latest menu + a default
        category, as ONE atomic transaction: every INSERT runs before a single
        commit, and ANY failure rolls the whole thing back — no orphaned rows.
        """
        from app.core.security import get_password_hash

        CarevoService.check_register_rate_limit(client_ip)

        taken = (await db.execute(
            text("SELECT 1 FROM users WHERE username = :u LIMIT 1"),
            {"u": payload.username},
        )).first()
        if taken:
            raise HTTPException(status_code=409, detail="Username already taken")

        # Resolve the city BEFORE anything is written (migration 013).
        # Exactly one of city / requested_city is accepted — the schema enforces
        # that. A named city must already be active in the canonical list, so
        # free-text spellings can no longer enter `outlets.city`; a requested one
        # is recorded as pending for admin approval further down.
        city_name = None
        requested_city = (getattr(payload, "requested_city", None) or "").strip()
        if payload.city:
            row = (await db.execute(text(
                "SELECT name FROM cities WHERE lower(name) = lower(:n) "
                "AND status = 'active' LIMIT 1"
            ), {"n": payload.city.strip()})).first()
            if not row:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "That city is not available yet. Pick one from the list, "
                        "or request a new city."
                    ),
                )
            # Store the canonical spelling, not whatever casing was submitted.
            city_name = row[0]
        else:
            city_name = requested_city

        try:
            org_id = (await db.execute(text(
                "INSERT INTO organizations (id, name, created_at) "
                "VALUES (gen_random_uuid(), :n, now()) RETURNING id"
            ), {"n": payload.restaurant_name})).scalar()

            outlet_id = (await db.execute(text(
                "INSERT INTO outlets (id, location_name, city, locality, phone_number, "
                "  latitude, longitude, "
                "  geofence_radius_meters, organization_id, verification_status, is_visible, "
                "  upi_id, created_at) "
                "VALUES (gen_random_uuid(), :ln, :city, :locality, :phone, :lat, :lng, 100, :org, "
                "        'pending_verification', false, :upi, now()) RETURNING id"
            ), {
                "ln": payload.restaurant_name, "city": city_name,
                "locality": (payload.locality or "").strip(),
                "phone": (payload.phone_number or "").strip() or None,
                "lat": payload.latitude, "lng": payload.longitude, "org": str(org_id),
                "upi": payload.upi_id,
            })).scalar()

            # New-city request rides the SAME pending-approval pattern as outlet
            # verification: a row with status='pending' that an admin approves or
            # rejects, audited through admin_audit_logs. No second queue.
            #
            # ON CONFLICT DO NOTHING: if another owner already requested the same
            # city (or it exists rejected), do not duplicate the row — the outlet
            # still carries the name and rides the existing request's decision.
            if requested_city:
                await db.execute(text("""
                    INSERT INTO cities (name, status, requested_by_outlet_id)
                    VALUES (:n, 'pending', :oid)
                    ON CONFLICT (lower(name)) DO NOTHING
                """), {"n": requested_city, "oid": str(outlet_id)})

            # email lands on the USER row (migration 015): password recovery is
            # per-account, and an outlet can have several staff users.
            taken_email = (await db.execute(text(
                "SELECT 1 FROM users WHERE lower(email) = lower(:e) LIMIT 1"
            ), {"e": payload.email})).first()
            if taken_email:
                raise HTTPException(
                    status_code=409, detail="That email is already registered"
                )

            await db.execute(text(
                # is_outlet_owner = true (migration 037). THIS is the account
                # that runs the restaurant, and saying so explicitly is what
                # replaced the old "it has no roles, so it must be the owner"
                # inference — an inference a waiter could satisfy by minting a
                # role-less account through the then-open /api/v1/users.
                "INSERT INTO users (id, username, hashed_password, is_active, outlet_id, "
                "  email, is_outlet_owner, created_at) "
                "VALUES (gen_random_uuid(), :u, :pw, true, :oid, :email, true, now())"
            ), {
                "u": payload.username, "pw": get_password_hash(payload.password),
                "oid": str(outlet_id), "email": payload.email.strip().lower(),
            })

            menu_id = (await db.execute(text(
                "INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) "
                "VALUES (gen_random_uuid(), :oid, 'v1', true, now()) RETURNING id"
            ), {"oid": str(outlet_id)})).scalar()

            # Seed a sensible default set so the owner can add dishes immediately
            # (the dish form's category picker has real options from the start).
            # Owners can still add/rename their own categories on top of these.
            for _pos, _name in enumerate(DEFAULT_CATEGORIES):
                await db.execute(text(
                    "INSERT INTO categories (id, menu_id, name, created_at) "
                    "VALUES (gen_random_uuid(), :mid, :name, now())"
                ), {"mid": str(menu_id), "name": _name})

            # Single commit: all rows persist together, or none do.
            await db.commit()
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            # Includes the users.username UNIQUE race → clean rollback, no orphans.
            await db.rollback()
            raise HTTPException(status_code=500, detail="Registration failed")

        return {
            "outlet_id": outlet_id,
            "username": payload.username,
            "verification_status": "pending_verification",
            "message": "Registered. Pending admin verification before your outlet is visible to customers.",
        }

    @staticmethod
    async def set_item_availability(
        db: AsyncSession, item_id: uuid.UUID, outlet_id: uuid.UUID, is_available: bool
    ) -> dict:
        # Ownership guard: item must belong to a latest menu of the caller's outlet.
        owns = (await db.execute(text("""
            SELECT 1 FROM menu_items mi
            JOIN categories c ON c.id = mi.category_id
            JOIN menus m ON m.id = c.menu_id
            WHERE mi.id = :iid AND m.outlet_id = :oid
            LIMIT 1
        """), {"iid": str(item_id), "oid": str(outlet_id)})).first()
        if not owns:
            raise HTTPException(status_code=404, detail="Menu item not found for this outlet")
        row = (await db.execute(text(
            "UPDATE menu_items SET is_available = :v WHERE id = :iid RETURNING id, is_available"
        ), {"v": is_available, "iid": str(item_id)})).first()
        await db.commit()
        return {"id": row[0], "is_available": bool(row[1])}

    @staticmethod
    async def list_active_orders(db: AsyncSession, outlet_id: uuid.UUID) -> list[dict]:
        """Active customer_orders for the outlet, newest first. NAME-FREE."""
        # Scheduled-pickup releases run FIRST, before the expiry sweep, and the
        # order of these two is not stylistic (migration 031).
        #
        # Releasing clears release_at and hands the order to advance_status,
        # which stamps updated_at=now(). Sweeping first would mean a just-due
        # order is examined by the TTL check while it still carries the
        # updated_at from payment — hours old — and although the sweeper's
        # `release_at IS NULL` clause already protects it, relying on that
        # ordering-independence twice over costs nothing and removes the whole
        # class of question. Release, then sweep, then list.
        #
        # This is the PRIMARY release mechanism, not a backup: the owner app
        # polls here every 15 seconds while the tablet is open, and the
        # background poller cannot be trusted alone on a free-tier instance
        # that sleeps. Wrapped for the same reason the train notify is — a
        # release failure must never stop the owner seeing their queue.
        try:
            await CarevoService.refresh_scheduled_releases(db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # Sweep expired pickups so the queue never shows stale orders.
        await CarevoService._expire_stale_pickups(db, outlet_id=outlet_id)
        # Same check-on-read slot: push the kitchen for any train order that has
        # become due. Wrapped because a notification failure must never stop the
        # owner seeing their order queue.
        try:
            await CarevoService._notify_kitchen_for_due_trains(db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # Manual acceptance (032): advance the alert ladder and expire anything
        # past its deadline, on the SAME check-on-read principle.
        #
        # This is not a backup for the durable poller, it is a co-equal driver.
        # owner_app polls here every 15 seconds while the tablet is open, and a
        # free-tier instance that has gone to sleep runs no poller at all — so
        # for a 180-second deadline, the staff poll is frequently the only
        # thing that can fire it. Both drivers are safe to overlap because
        # every transition in AcceptanceService is a compare-and-set.
        try:
            from app.modules.carevo_customer.acceptance import AcceptanceService
            await AcceptanceService.process_acceptance_deadlines(
                db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # Stock reservations (033): reclaim HELD holds on UNPAID orders past
        # their expiry. Same check-on-read slot and the same reason — there is
        # no sweeper for unpaid orders anywhere else, because _LIVE_STATUSES
        # excludes CREATED, so without this an abandoned checkout holds the
        # last portion of a dish until the process restarts.
        try:
            from app.modules.carevo_customer.stock import StockService
            await StockService.sweep_expired(db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # Contact redaction (034): destroy pay-at-pickup contact snapshots past
        # their retention. SAME check-on-read slot as every sweep above, and
        # for the same reason — this deploy has no reliable scheduler, and a
        # retention promise that only holds while a worker happens to be awake
        # is not a retention promise.
        try:
            await CarevoService.redact_expired_contacts(db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # Direct UPI (035): cancel orders nobody claimed to have paid within
        # the pay window. Same check-on-read slot and the same reason — the
        # CREATED status these sit in is invisible to _expire_stale_pickups,
        # so without this they would hold stock and block the customer's next
        # order until the reservation TTL happened to notice.
        try:
            await CarevoService.expire_unclaimed_upi_orders(db, outlet_id=outlet_id)
        except Exception:
            await db.rollback()
        # A verified pickup lingers for COMPLETED_GRACE, then drops out on its
        # own. It used to vanish the instant staff tapped verify, which left no
        # window to notice a mistake — and no way to confirm the right order was
        # closed. The cutoff is computed from pickup_verified_at IN SQL, not
        # from a client timer, so closing and reopening the app cannot revive a
        # row that has already aged out, and two devices always agree.
        #
        # Order history and the admin order log read their own queries and are
        # untouched: this thins the live kitchen queue only.
        # Orders predating the outlet's rename belong to its previous identity
        # and are hidden here. Cosmetic: the rows are untouched and the admin
        # order log still shows all of them. See CarevoService.RENAME_CUTOFF.
        orders = (await db.execute(text("""
            SELECT id, status, payment_status, is_locked, total_amount,
                   created_at, pickup_verified_at,
                   -- Manual acceptance (032). ADDITIVE: NULL for every order
                   -- at an auto outlet, so the rows owner_app already renders
                   -- are byte-identical.
                   acceptance_state, acceptance_deadline_at,
                   -- Pay at pickup (034). All NULL/0 for a prepaid order.
                   payment_mode, call_state, call_attempts,
                   collected_payment_method,
                   -- Direct UPI (035), additive and NULL/false for every
                   -- other mode.
                   payment_claimed_at, manual_refund_due, manual_refund_reason,
                   -- CONTACT VISIBILITY, DECIDED IN SQL.
                   --
                   -- Computed here rather than in Python so there is no path
                   -- that reads the columns and then forgets to apply the
                   -- window: the contact is either selected visible or
                   -- selected NULL, and the serialiser never sees a value it
                   -- is supposed to hide. A redacted row has nothing to show
                   -- either way.
                   --
                   -- Visible while the order is LIVE, plus a grace period
                   -- after it finishes: a disputed handover and a no-show
                   -- callback both happen inside the hour, and the restaurant
                   -- may need to ring back about food it is holding.
                   CASE WHEN payment_mode = ANY(:nongw)
                             AND contact_redacted_at IS NULL
                             AND (upper(coalesce(status, '')) <> ALL(:cterm)
                                  OR updated_at > now() - CAST(:cgrace AS interval))
                        THEN contact_name ELSE NULL END AS contact_name,
                   CASE WHEN payment_mode = ANY(:nongw)
                             AND contact_redacted_at IS NULL
                             AND (upper(coalesce(status, '')) <> ALL(:cterm)
                                  OR updated_at > now() - CAST(:cgrace AS interval))
                        THEN contact_phone ELSE NULL END AS contact_phone
            FROM customer_orders
            WHERE outlet_id = :oid
              AND created_at >= :rename_cutoff
              -- Scheduled pickup (031). A held order is payment-confirmed and
              -- genuinely live, so it passes the status floor below — this is
              -- the clause that keeps it off the tablet until its moment.
              --
              -- The TIME form, deliberately, and NOT the sweeper's state form:
              -- the question here is "may the restaurant see it yet", and being
              -- eager is harmless. If release_at has passed but the release has
              -- not executed (poller asleep, first request after a cold start),
              -- the order still appears — correct, since it IS due — and the
              -- refresh call above will have executed it on this very request
              -- in all but the narrowest race.
              AND (release_at IS NULL OR release_at <= now())
              AND (
                    -- Payment-confirmed and still live. Reuses _LIVE_STATUSES
                    -- (the same set the expiry sweep uses) as the floor, which
                    -- deliberately excludes CREATED: an unpaid order must not
                    -- reach restaurant staff until payment succeeds. Every live
                    -- status (RECEIVED -> PREPARING -> READY, plus PAID) is in
                    -- the set; CREATED is the only one it drops.
                    status = ANY(:live)
                 OR (
                      status = 'COMPLETED'
                      AND pickup_verified_at IS NOT NULL
                      AND pickup_verified_at >= now() - CAST(:grace AS interval)
                    )
                 -- PAY AT PICKUP, awaiting its confirmation call (034).
                 --
                 -- The one admitted exception to the paid/live floor above,
                 -- and it does not weaken it: this order is not unpaid-because-
                 -- -checkout-is-still-open, it is unpaid BY DESIGN, and the
                 -- restaurant is the only party who can move it forward. The
                 -- floor's purpose — keep half-finished checkouts off the
                 -- tablet — is untouched, because a PREPAID order in CREATED
                 -- still does not match.
                 --
                 -- Narrow on all three axes deliberately: the mode, the
                 -- status, AND an acceptance_state of AWAITING. An expired or
                 -- rejected pickup order has moved to CANCELLED and drops out
                 -- on the status clause; one that is accepted is RECEIVED and
                 -- matches the floor like anything else.
                 -- Both non-gateway modes (035). A direct-UPI order reaches
                 -- AWAITING at the CLAIM rather than at placement, so an
                 -- unclaimed one is correctly absent: there is nothing for the
                 -- restaurant to do until the customer says they have paid.
                 OR (
                      payment_mode = ANY(:nongw)
                      AND status = 'CREATED'
                      AND acceptance_state = 'AWAITING'
                    )
              )
            ORDER BY created_at DESC
        """), {
            "oid": str(outlet_id),
            "rename_cutoff": CarevoService.RENAME_CUTOFF,
            # The paid/live floor — same definition the expiry sweep uses, not a
            # duplicated literal. CREATED (unpaid) is absent from it by design.
            "live": list(_LIVE_STATUSES),
            # A timedelta, not a string: the CAST tells asyncpg to expect an
            # interval, and it maps timedelta -> interval natively while
            # rejecting '1800 seconds' outright.
            "grace": CarevoService.COMPLETED_GRACE,
            # Contact-visibility window (034). Same timedelta-not-string rule.
            "cterm": list(_CONTACT_TERMINAL_STATUSES),
            "cgrace": CONTACT_VISIBLE_AFTER_TERMINAL,
            "nongw": list(_NON_GATEWAY_METHODS),
        })).fetchall()
        if not orders:
            return []
        order_ids = [str(o.id) for o in orders]
        items = (await db.execute(text("""
            SELECT id, customer_order_id, name_snap, quantity
            FROM customer_order_items
            WHERE customer_order_id = ANY(:ids)
            ORDER BY created_at
        """), {"ids": order_ids})).fetchall()
        by_order: dict = defaultdict(list)
        for it in items:
            by_order[str(it.customer_order_id)].append(
                {"id": it.id, "name": it.name_snap, "quantity": it.quantity}
            )

        # --- Customer arrival signals (owner_app chip) -----------------------
        #
        # ONE batched query over the whole page for all three new fields —
        # departed_at, arrived_at (order_events) AND est_arrival_at
        # (order_twin) — never one query per order and never a second round
        # trip for the second source. MAX(occurred_at) FILTER is the "latest
        # per type" aggregate: at most one CUSTOMER_DEPARTED and one
        # CUSTOMER_ARRIVED row exist per order in practice (both writers
        # check-then-write exactly once — see record_departed/record_arrived),
        # so MAX is exact, not just a safe upper bound. The two CTEs are each
        # already scoped to :ids before the join, so the FULL OUTER JOIN can
        # never pull in another outlet's orders or another order's twin.
        #
        # No lat/lng/accuracy/speed is selected anywhere here — only
        # timestamps. The owner app has no legitimate use for a customer's
        # raw location.
        arrival_rows = (await db.execute(text("""
            WITH ev AS (
                SELECT order_id,
                       MAX(occurred_at) FILTER (
                           WHERE event_type = 'CUSTOMER_DEPARTED') AS departed_at,
                       MAX(occurred_at) FILTER (
                           WHERE event_type = 'CUSTOMER_ARRIVED') AS arrived_at
                FROM order_events
                WHERE order_id = ANY(:ids)
                  AND event_type IN ('CUSTOMER_DEPARTED', 'CUSTOMER_ARRIVED')
                GROUP BY order_id
            ),
            tw AS (
                SELECT order_id, arrival_p50
                FROM order_twin
                WHERE order_id = ANY(:ids) AND arrival_p50 IS NOT NULL
            )
            SELECT COALESCE(ev.order_id, tw.order_id) AS order_id,
                   ev.departed_at, ev.arrived_at, tw.arrival_p50 AS est_arrival_at
            FROM ev
            FULL OUTER JOIN tw ON tw.order_id = ev.order_id
        """), {"ids": order_ids})).fetchall()
        departed_by_order = {str(r.order_id): r.departed_at
                              for r in arrival_rows if r.departed_at is not None}
        arrived_by_order = {str(r.order_id): r.arrived_at
                             for r in arrival_rows if r.arrived_at is not None}
        est_arrival_by_order = {str(r.order_id): r.est_arrival_at
                                 for r in arrival_rows if r.est_arrival_at is not None}

        return [
            {
                "order_id": o.id,
                "status": o.status,
                "payment_status": o.payment_status,
                "is_locked": bool(o.is_locked),
                "total_amount": float(o.total_amount) if o.total_amount is not None else 0.0,
                "created_at": o.created_at,
                "pickup_verified_at": o.pickup_verified_at,
                # Manual acceptance (032), additive. NULL/None at an auto
                # outlet, which is what keeps owner_app's existing rendering
                # unchanged until it learns to read them.
                "acceptance_state": o.acceptance_state,
                "acceptance_deadline_at": o.acceptance_deadline_at,
                # Pay at pickup (034), additive. All None/0 for a prepaid
                # order. contact_* arrive already suppressed by the SQL above,
                # so there is nothing to re-check here — which is the point of
                # deciding it there.
                "payment_mode": o.payment_mode,
                "contact_first_name": CarevoService._first_name(o.contact_name),
                "contact_phone": o.contact_phone,
                "contact_visible": bool(o.contact_phone),
                "call_state": o.call_state,
                "call_attempts": int(o.call_attempts or 0),
                "collected_payment_method": o.collected_payment_method,
                # Direct UPI (035), additive.
                "payment_claimed_at": o.payment_claimed_at,
                "manual_refund_due": bool(o.manual_refund_due),
                "manual_refund_reason": o.manual_refund_reason,
                "departed_at": departed_by_order.get(str(o.id)),
                "arrived_at": arrived_by_order.get(str(o.id)),
                "est_arrival_at": est_arrival_by_order.get(str(o.id)),
                "items": by_order.get(str(o.id), []),
            }
            for o in orders
        ]

    @staticmethod
    def _first_name(full_name: Optional[str]) -> Optional[str]:
        """The first whitespace-delimited token of a name, or None.

        A counter calling out an order needs "Asha"; a surname is extra
        personal data with no operational use. Done here rather than in SQL so
        the stored snapshot keeps the whole name — the restaurant is not the
        only future reader of that column, and truncating at rest would be
        irreversible.
        """
        if not full_name:
            return None
        first = full_name.strip().split()
        return first[0] if first else None

    @staticmethod
    async def redact_expired_contacts(
        db: AsyncSession, *, outlet_id=None
    ) -> int:
        """Destroy pay-at-pickup contact snapshots past their retention.

        The DURABLE half of the privacy promise. The owner queue stops
        RETURNING a contact two hours after the order finishes, but suppression
        only governs new reads — the row still holds the number. This is what
        actually removes it.

        SCOPED TO ONE OUTLET when called from the queue poll, and that scoping
        is load-bearing rather than tidy. Unscoped, this is a table-wide UPDATE
        on the hottest staff path in the product: it takes row locks across
        every outlet's orders, so one restaurant's 15-second poll can block on
        another restaurant's in-flight write, and the work it does grows with
        the whole table rather than with the caller. Every other sweep in that
        check-on-read slot is outlet-scoped for the same reason.
        [-] The cost of scoping: an outlet nobody polls does not redact. In
        practice the polling outlet is exactly the one whose data is at issue —
        a contact belongs to an order at that outlet — so the rows that matter
        are reached by the restaurant that holds them. A quiet outlet's
        contacts are also already suppressed at the API by then; what lingers
        is the row, not the exposure. Passing outlet_id=None still sweeps
        globally, which is what a future cron or an admin action should use.

        contact_redacted_at is stamped rather than left NULL so a redacted
        order stays distinguishable from a prepaid one that never had a
        contact — and so ck_customer_orders_pickup_contact keeps holding.

        Commits its own maintenance UPDATE, like _expire_stale_pickups.
        Idempotent: the predicate excludes rows it has already cleared.
        """
        clauses = [
            "payment_mode = ANY(:modes)",
            "contact_redacted_at IS NULL",
            "(contact_phone IS NOT NULL OR contact_name IS NOT NULL)",
            "created_at < now() - CAST(:after AS interval)",
        ]
        params: dict = {"modes": list(_NON_GATEWAY_METHODS),
                        "after": CONTACT_REDACTION_AFTER}
        if outlet_id is not None:
            clauses.append("outlet_id = :oid")
            params["oid"] = str(outlet_id)

        res = await db.execute(text(
            "UPDATE customer_orders "
            "   SET contact_name = NULL, contact_phone = NULL, "
            "       contact_redacted_at = now() "
            " WHERE " + " AND ".join(clauses)
        ), params)
        if res.rowcount:
            await db.commit()
            logger.info("redacted %s pay-at-pickup contact snapshot(s)",
                        res.rowcount)
        return res.rowcount or 0

    @staticmethod
    async def mark_order_paid_by_staff(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID
    ) -> dict:
        """Manual-tick payment confirmation (UPI-intent MVP). Staff confirm the
        payment landed in their UPI app; this flips the order to PAID, issues the
        pickup_code, and broadcasts — surfacing the order as confirmed to the
        customer. Ownership-scoped and idempotent (via mark_paid)."""
        res = await db.execute(select(CustomerOrder).where(CustomerOrder.id == order_id))
        order = res.scalars().first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")
        # A finished order cannot be reopened by a payment — same rule as the
        # webhook. Raised here rather than inside mark_paid, because the two
        # callers need opposite things from a refusal: the gateway must get a
        # 200 or it retries forever, whereas staff who just tapped "mark paid"
        # must be TOLD it did not happen. A 200 carrying an unchanged status
        # would read as success.
        if (order.status or "").upper() in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"This order is {order.status} and can no longer be "
                       f"marked paid.")
        order = await CarevoService.mark_paid(db, order, method="upi_manual")
        return {
            "order_id": order.id,
            "status": order.status,
            "payment_status": order.payment_status,
            "pickup_code": order.pickup_code,
        }

    @staticmethod
    async def notify_order(
        db: AsyncSession,
        order_id: uuid.UUID,
        outlet_id: uuid.UUID,
        notify_type: str,
        item_id: Optional[uuid.UUID],
    ) -> dict:
        valid = {"ready_now", "delayed_10", "item_unavailable"}
        if notify_type not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid type. Must be one of: {sorted(valid)}",
            )

        # Order must exist and belong to the caller's outlet.
        order = (await db.execute(text(
            "SELECT id, outlet_id, status FROM customer_orders WHERE id = :oid"
        ), {"oid": str(order_id)})).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=403, detail="Order does not belong to your outlet")

        item_name: Optional[str] = None
        resolved_item_id: Optional[uuid.UUID] = None

        if notify_type == "item_unavailable":
            # Same cutoff as the batch endpoint. This single-item path is the
            # older one and is still reachable, so guarding only the checklist
            # would leave the hole open through a different door.
            CarevoService._assert_composition_open(order.status)
            if item_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="item_id is required when type is 'item_unavailable'",
                )
            line = (await db.execute(text("""
                SELECT id, name_snap FROM customer_order_items
                WHERE id = :iid AND customer_order_id = :oid
            """), {"iid": str(item_id), "oid": str(order_id)})).first()
            if not line:
                raise HTTPException(
                    status_code=400,
                    detail="item_id is not a line item of this order",
                )
            resolved_item_id = line.id
            item_name = line.name_snap
        # For ready_now / delayed_10, item_id is ignored (kept null).

        messages = {
            "ready_now": "Your order is ready for pickup.",
            "delayed_10": "Your order is delayed by about 10 minutes.",
            "item_unavailable": f"'{item_name}' is unavailable and won't be prepared.",
        }
        payload = {
            "event": "notify",
            "order_id": str(order_id),
            "type": notify_type,
            "item_id": str(resolved_item_id) if resolved_item_id else None,
            "item_name": item_name,
            "message": messages[notify_type],
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # PE Step 2: "Ready now" is the one genuine readiness signal the owner
        # already gives (no separate kitchen taps), so it emits ORDER_READY.
        # item_unavailable is recorded too (affects composition + hold tolerance).
        if notify_type == "ready_now":
            await pe.write_event(
                db, order_id, pe.ORDER_READY,
                actor_type="staff", source="tap", outlet_id=outlet_id,
            )
            await db.commit()
        elif notify_type == "item_unavailable":
            await pe.write_event(
                db, order_id, pe.ITEM_UNAVAILABLE,
                actor_type="staff", source="tap", outlet_id=outlet_id,
                payload={"item_id": str(resolved_item_id) if resolved_item_id else None},
            )
            await db.commit()

        # Best-effort delivery: delivered reflects whether any socket is connected.
        delivered = bool(customer_manager.active_connections.get(str(order_id)))
        try:
            await customer_manager.send_order_update(str(order_id), payload)
        except Exception:
            delivered = False

        return {
            "ok": True,
            "delivered": delivered,
            "type": notify_type,
            "item_id": resolved_item_id,
            "item_name": item_name,
        }

    # Tombstone marker for a deleted account, written to google_uid.
    #
    # It has to go SOMEWHERE, because customers_identity_present CHECKs that
    # phone_number OR google_uid is non-null, and the row must survive to hold
    # order history together (customer_orders.customer_id is RESTRICT).
    #
    # google_uid rather than phone_number for two concrete reasons:
    #   * phone_number is varchar(20) — "deleted:" + a 36-char uuid is 44 chars
    #     and does not fit. google_uid is varchar(128).
    #   * putting it here lets phone_number be set to NULL, i.e. genuinely
    #     erased, which is the better privacy outcome anyway.
    # The uuid makes it unique by construction (google_uid has a partial unique
    # index) and "deleted:<uuid>" can never match a real Google UID, so no
    # sign-in path can find a tombstone and resurrect the dead account.
    DELETED_UID_PREFIX = "deleted:"

    @staticmethod
    def is_deleted_customer(google_uid: Optional[str]) -> bool:
        return bool(google_uid and google_uid.startswith(
            CarevoService.DELETED_UID_PREFIX))

    @staticmethod
    async def delete_my_account(db: AsyncSession, customer: Customer) -> dict:
        """Irreversibly erase the customer's personal data (Play Store requires
        an in-app deletion route for apps with accounts).

        NOT a row DELETE, and that is forced by the schema, not a preference:
        customer_orders.customer_id is RESTRICT, so deleting the row fails for
        anyone who has ever ordered — and cascading it would destroy the
        restaurants' revenue records along with the customer.

        So: anonymise in place. Every identifier is overwritten or nulled, the
        row survives only as an unusable tombstone holding the orders together.

        ERASED  — name, phone, email, google_uid, device token, points balance,
                  premium window, unspent coupons, notification history.
        RETAINED— order rows and their line items (business/tax records, as the
                  privacy policy states), plus points/promotion ledgers, which
                  carry ids and amounts but no personal data.

        Login is impossible afterwards: the tombstoned phone matches no real
        number and google_uid is gone, so neither sign-in path can find it.
        """
        cid = str(customer.id)

        # Personal content first, so a failure part-way cannot leave the
        # identity erased while their data lingers.
        await db.execute(text("DELETE FROM coupons WHERE customer_id = :c"), {"c": cid})
        await db.execute(
            text("DELETE FROM push_notifications WHERE customer_id = :c"), {"c": cid})

        row = (await db.execute(text("""
            UPDATE customers
            SET name = NULL,
                email = NULL,
                phone_number = NULL,
                fcm_token = NULL,
                fcm_token_updated_at = NULL,
                points_balance = 0,
                premium_until = NULL,
                google_uid = :prefix || id::text
            WHERE id = :c
            RETURNING id
        """), {"c": cid, "prefix": CarevoService.DELETED_UID_PREFIX})).first()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")

        retained = (await db.execute(text(
            "SELECT count(*) FROM customer_orders WHERE customer_id = :c"), {"c": cid}
        )).scalar() or 0

        await db.commit()
        return {
            "ok": True,
            "deleted": True,
            "orders_retained": int(retained),
            "message": (
                "Your account and personal details have been deleted. "
                "Past order records are kept for the restaurants' tax and "
                "accounting obligations, and are no longer linked to you."
            ),
        }

    @staticmethod
    async def register_staff_push_token(
        db: AsyncSession, user_id: uuid.UUID, fcm_token: str
    ) -> dict:
        """Store a staff device token (migration 017). Last device wins, same
        one-token-per-account model customers already use."""
        await db.execute(text("""
            UPDATE users SET fcm_token = :t, fcm_token_updated_at = now()
            WHERE id = :uid
        """), {"t": fcm_token.strip(), "uid": str(user_id)})
        await db.commit()
        return {"ok": True, "registered": True}

    @staticmethod
    async def mark_items_unavailable(
        db: AsyncSession, order_id: uuid.UUID, outlet_id: uuid.UUID,
        item_ids: list,
    ) -> dict:
        """Batch N/A: several line items, one staff action.

        Deliberately NOT one event for the batch. Each item gets its own
        ITEM_UNAVAILABLE event and its own push naming that dish, because:
          * the prediction engine reads composition per item;
          * "2 items unavailable" tells the customer nothing actionable.

        Does NOT touch the order total. The original paid order stands as-is;
        adjusting it here would be a second money path (refunds are manual and
        off-app by decision), and the customer's remedy is to place a NEW order
        for replacements.
        """
        # Ownership first — never leak whether an order id exists elsewhere.
        order = (await db.execute(text(
            "SELECT id, outlet_id, status FROM customer_orders WHERE id = :oid"
        ), {"oid": str(order_id)})).first()
        if not order or str(order.outlet_id) != str(outlet_id):
            raise HTTPException(status_code=404, detail="Order not found for this outlet")
        # Cutoff: once the food is made, "won't be prepared" is simply untrue.
        CarevoService._assert_composition_open(order.status, count=len(item_ids))

        # Collapse duplicates but keep the submitted order for stable output.
        seen, wanted = set(), []
        for i in item_ids:
            if str(i) not in seen:
                seen.add(str(i))
                wanted.append(str(i))

        rows = (await db.execute(text("""
            SELECT id, name_snap FROM customer_order_items
            WHERE customer_order_id = :oid AND id = ANY(:ids)
        """), {"oid": str(order_id), "ids": wanted})).fetchall()
        found = {str(r.id): r.name_snap for r in rows}

        missing = [i for i in wanted if i not in found]
        if missing:
            # All-or-nothing: a checklist that half-applies is worse than one
            # that refuses, because staff cannot see which half took.
            raise HTTPException(
                status_code=400,
                detail=f"{len(missing)} of the selected items are not line items of this order",
            )

        now = datetime.now(timezone.utc)
        marked = []
        for iid in wanted:
            await pe.write_event(
                db, order_id, pe.ITEM_UNAVAILABLE,
                actor_type="staff", source="tap", outlet_id=outlet_id,
                payload={"item_id": iid, "batch_size": len(wanted)},
            )
        await db.commit()

        # WS first (instant in-app banner), then FCM for a backgrounded app.
        delivered_any = False
        for iid in wanted:
            name = found[iid]
            payload = {
                "event": "notify",
                "order_id": str(order_id),
                "type": "item_unavailable",
                "item_id": iid,
                "item_name": name,
                "message": f"'{name}' is unavailable and won't be prepared.",
                "ts": now.isoformat(),
            }
            delivered = bool(customer_manager.active_connections.get(str(order_id)))
            try:
                await customer_manager.send_order_update(str(order_id), payload)
            except Exception:
                delivered = False
            delivered_any = delivered_any or delivered
            marked.append({"item_id": iid, "name": name, "notified": delivered})

        # One push per item, naming the dish. Best-effort throughout.
        try:
            from app.modules.push.service import PushService, KIND_ITEM_UNAVAILABLE
            cust = (await db.execute(text(
                "SELECT customer_id FROM customer_orders WHERE id = :oid"
            ), {"oid": str(order_id)})).scalar()
            if cust:
                for iid in wanted:
                    await PushService.send(
                        db, customer_id=cust, kind=KIND_ITEM_UNAVAILABLE,
                        title="Item unavailable",
                        body=f"'{found[iid]}' can't be prepared. "
                             f"Tap to reorder something else.",
                        order_id=order_id,
                        data={"item_id": iid, "item_name": found[iid] or ""},
                    )
        except Exception:
            await db.rollback()

        return {
            "ok": True,
            "order_id": order_id,
            "marked": marked,
            "delivered": delivered_any,
        }

    # ==================== Profile / loyalty / coupons (010) ====================
    # Accrual rate: 0.10 points per Rs.20 spent, i.e. points = amount * 0.005.
    # A Rs.10,000 lifetime spend reaches the 50-point threshold, which mints a
    # Rs.100 coupon - 1% back. Constants live here so clients never hardcode them.
    POINTS_PER_RUPEE = 0.10 / 20.0
    REDEMPTION_THRESHOLD = 50.0
    REDEMPTION_VALUE_RUPEES = 100.0
    PREMIUM_TRIAL_DAYS = 60

    @staticmethod
    def _plan_label(premium_until: Optional[datetime]) -> str:
        """Derive the plan from premium_until. Never stored - see MeOut."""
        if premium_until is None:
            return "Free"
        # Rows written before 010 may come back naive; treat those as UTC rather
        # than raising on an aware/naive comparison.
        if premium_until.tzinfo is None:
            premium_until = premium_until.replace(tzinfo=timezone.utc)
        return "Premium" if premium_until > datetime.now(timezone.utc) else "Free"

    @staticmethod
    def _me_payload(customer: Customer) -> dict:
        return {
            "id": customer.id,
            "name": customer.name,
            "phone_number": customer.phone_number,
            "email": customer.email,
            "points_balance": float(customer.points_balance or 0),
            "premium_until": customer.premium_until,
            "plan": CarevoService._plan_label(customer.premium_until),
        }

    @staticmethod
    async def get_me(db: AsyncSession, customer: Customer) -> dict:
        return CarevoService._me_payload(customer)

    @staticmethod
    async def update_me(db: AsyncSession, customer: Customer, payload) -> dict:
        """Name only. Phone and email are verified identities, not client-settable."""
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name cannot be empty")
        customer.name = name
        await db.commit()
        await db.refresh(customer)
        return CarevoService._me_payload(customer)

    @staticmethod
    async def list_my_orders(
        db: AsyncSession, customer: Customer, limit: int = 50
    ) -> list[dict]:
        """The signed-in customer's own order history, newest first.

        Scoped by customer_id taken from the bearer token - never from a
        client-supplied id - so one customer can never read another's orders.

        Also honours `customers.history_cutoff_at` (migration 022): orders
        created before it are omitted. NULL - every account but the three
        retired development ones - means no cutoff and changes nothing.

        This is a VIEW filter on one endpoint, not a delete. The rows stay
        exactly where they are and remain visible to owner_app's queue, the
        admin order log and the prediction engine. Clearing the column restores
        them here instantly. That distinction matters: `order_events` and
        `prediction_log` carry BEFORE DELETE immutability triggers, so those
        orders cannot be removed even deliberately, and pretending otherwise by
        hiding them everywhere would misrepresent what actually happened.
        """
        orders = (await db.execute(text("""
            SELECT co.id, co.outlet_id, o.location_name AS outlet_name,
                   co.status, co.payment_status, co.total_amount,
                   co.discount_amount, co.created_at,
                   -- Needed so history can surface the pickup code for an
                   -- order still in progress. Before this the code existed
                   -- only on the transient post-checkout screen, so leaving
                   -- that screen lost it permanently.
                   co.pickup_code
            FROM customer_orders co
            LEFT JOIN outlets o ON o.id = co.outlet_id
            WHERE co.customer_id = :cid
              -- Read off the Customer already resolved from the token, so no
              -- join is needed. NULL cutoff short-circuits to "show all".
              AND (CAST(:cutoff AS timestamptz) IS NULL
                   OR co.created_at >= CAST(:cutoff AS timestamptz))
            ORDER BY co.created_at DESC
            LIMIT :limit
        """), {
            "cid": str(customer.id),
            "cutoff": getattr(customer, "history_cutoff_at", None),
            "limit": limit,
        })).fetchall()
        if not orders:
            return []

        order_ids = [str(o.id) for o in orders]
        items = (await db.execute(text("""
            SELECT customer_order_id, name_snap, quantity
            FROM customer_order_items
            WHERE customer_order_id = ANY(:ids)
            ORDER BY created_at
        """), {"ids": order_ids})).fetchall()
        by_order: dict = defaultdict(list)
        for it in items:
            by_order[str(it.customer_order_id)].append(
                {"name": it.name_snap, "quantity": it.quantity}
            )

        return [
            {
                "order_id": o.id,
                "outlet_id": o.outlet_id,
                "outlet_name": o.outlet_name,
                "status": o.status,
                "payment_status": o.payment_status,
                "total_amount": float(o.total_amount or 0),
                "discount_amount": float(o.discount_amount or 0),
                "created_at": o.created_at,
                "pickup_code": o.pickup_code,
                "items": by_order.get(str(o.id), []),
            }
            for o in orders
        ]

    @staticmethod
    async def _accrue_points(db: AsyncSession, order: CustomerOrder) -> None:
        """Award points for a paid order. Called inside mark_paid's transaction.

        Earned on what was actually paid (total_amount, already net of any
        discount): a redeemed coupon should not also re-earn points on the part
        it paid for.
        """
        if order.customer_id is None:
            return
        amount = float(order.total_amount or 0)
        points = round(amount * CarevoService.POINTS_PER_RUPEE, 2)
        if points <= 0:
            return

        # Idempotency guard mirroring the partial unique index in migration 010:
        # mark_paid is itself idempotent, but a retry must never double-award.
        already = (await db.execute(text("""
            SELECT 1 FROM point_transactions
            WHERE order_id = :oid AND reason = 'ORDER_ACCRUAL' LIMIT 1
        """), {"oid": str(order.id)})).first()
        if already:
            return

        db.add(PointTransaction(
            customer_id=order.customer_id,
            order_id=order.id,
            points_delta=points,
            reason="ORDER_ACCRUAL",
        ))
        # Increment in SQL rather than read-modify-write: two orders settling at
        # the same moment must not clobber each other's award.
        await db.execute(text("""
            UPDATE customers SET points_balance = COALESCE(points_balance, 0) + :p
            WHERE id = :cid
        """), {"p": points, "cid": str(order.customer_id)})

    @staticmethod
    async def get_points(db: AsyncSession, customer: Customer) -> dict:
        rows = (await db.execute(text("""
            SELECT id, order_id, points_delta, reason, created_at
            FROM point_transactions
            WHERE customer_id = :cid
            ORDER BY created_at DESC
            LIMIT 50
        """), {"cid": str(customer.id)})).fetchall()
        balance = float(customer.points_balance or 0)
        return {
            "points_balance": balance,
            "redemption_threshold": CarevoService.REDEMPTION_THRESHOLD,
            "redemption_value_rupees": CarevoService.REDEMPTION_VALUE_RUPEES,
            "can_redeem": balance >= CarevoService.REDEMPTION_THRESHOLD,
            "transactions": [
                {
                    "id": r.id,
                    "order_id": r.order_id,
                    "points_delta": float(r.points_delta),
                    "reason": r.reason,
                    "created_at": r.created_at,
                }
                for r in rows
            ],
        }

    @staticmethod
    def _make_coupon_code(prefix: str) -> str:
        """Unambiguous alphabet: no O/0/I/1, so a code read aloud survives."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        body = "".join(secrets.choice(alphabet) for _ in range(8))
        return prefix + "-" + body

    @staticmethod
    async def redeem_points(db: AsyncSession, customer: Customer) -> dict:
        """Spend REDEMPTION_THRESHOLD points to mint one Rs.100 discount coupon."""
        threshold = CarevoService.REDEMPTION_THRESHOLD

        # Read the balance BEFORE the UPDATE, while `customer` is still a live
        # ORM object. The failure path below rolls back, which expires every
        # loaded attribute — touching customer.points_balance after that would
        # trigger a lazy refresh outside the greenlet context and raise
        # MissingGreenlet, turning an intended 409 into a 500.
        current_balance = float(customer.points_balance or 0)

        # The conditional UPDATE is the whole concurrency guard: two simultaneous
        # redemptions cannot both pass, because the second sees the debited
        # balance and matches no row.
        debited = (await db.execute(text("""
            UPDATE customers
            SET points_balance = points_balance - :t
            WHERE id = :cid AND COALESCE(points_balance, 0) >= :t
            RETURNING points_balance
        """), {"t": threshold, "cid": str(customer.id)})).first()
        if not debited:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail=(
                    "Not enough points. You need {:g} to redeem (you have {:g})."
                ).format(threshold, current_balance),
            )

        coupon = Coupon(
            code=CarevoService._make_coupon_code("PTS"),
            customer_id=customer.id,
            kind=Coupon.KIND_POINTS_DISCOUNT,
            discount_amount=CarevoService.REDEMPTION_VALUE_RUPEES,
            status="ACTIVE",
        )
        db.add(coupon)
        db.add(PointTransaction(
            customer_id=customer.id,
            order_id=None,  # not tied to an order until the coupon is spent
            points_delta=-threshold,
            reason="COUPON_REDEMPTION",
        ))
        await db.commit()
        await db.refresh(coupon)
        await db.refresh(customer)

        return {
            "coupon": {
                "id": coupon.id,
                "code": coupon.code,
                "kind": coupon.kind,
                "discount_amount": float(coupon.discount_amount),
                "trial_days": coupon.trial_days,
                "status": coupon.status,
                "expires_at": coupon.expires_at,
                "created_at": coupon.created_at,
            },
            "points_balance": float(customer.points_balance or 0),
            "message": "Rs.{:g} coupon ready. Apply it at checkout.".format(
                CarevoService.REDEMPTION_VALUE_RUPEES
            ),
        }

    @staticmethod
    async def list_my_coupons(db: AsyncSession, customer: Customer) -> list[dict]:
        rows = (await db.execute(text("""
            SELECT id, code, kind, discount_amount, trial_days, status,
                   expires_at, created_at
            FROM coupons
            WHERE customer_id = :cid AND status = 'ACTIVE'
            ORDER BY created_at DESC
        """), {"cid": str(customer.id)})).fetchall()
        return [
            {
                "id": r.id,
                "code": r.code,
                "kind": r.kind,
                "discount_amount": float(r.discount_amount or 0),
                "trial_days": r.trial_days or 0,
                "status": r.status,
                "expires_at": r.expires_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    @staticmethod
    async def _consume_points_coupon(
        db: AsyncSession, customer: Customer, *, order_id, gross: float, code: str
    ) -> float:
        """Validate and burn a POINTS_DISCOUNT coupon; return the rupee discount.

        Runs inside create_order's open transaction, so a later failure there
        rolls the burn back with it and the coupon stays spendable.
        """
        code = (code or "").strip().upper()
        now = datetime.now(timezone.utc)

        # One UPDATE does lookup, ownership check, expiry check, status check and
        # the burn together - leaving no window between validating and spending.
        row = (await db.execute(text("""
            UPDATE coupons
            SET status = 'REDEEMED', redeemed_at = :now, redeemed_order_id = :oid
            WHERE code = :code
              AND kind = 'POINTS_DISCOUNT'
              AND status = 'ACTIVE'
              AND (customer_id IS NULL OR customer_id = :cid)
              AND (expires_at IS NULL OR expires_at > :now)
            RETURNING id, discount_amount
        """), {
            "now": now, "oid": str(order_id), "code": code, "cid": str(customer.id),
        })).first()

        if not row:
            # Deliberately one message for every failure mode (unknown / already
            # used / expired / someone else's): probing codes should not reveal
            # which of those is true.
            raise HTTPException(
                status_code=422, detail="That coupon code is not valid."
            )

        await db.execute(text(
            "UPDATE customer_orders SET coupon_id = :couid WHERE id = :oid"
        ), {"couid": str(row[0]), "oid": str(order_id)})

        # Cap at the order value, so the recorded discount is never larger than
        # what was actually taken off.
        return round(min(float(row[1] or 0), gross), 2)

    @staticmethod
    async def redeem_trial_coupon(db: AsyncSession, customer: Customer, payload) -> dict:
        """Redeem a PREMIUM_TRIAL coupon: extends premium_until by trial_days.

        No payment, no billing, no plan record - this grants a timestamp. Paid
        plans are a separate workstream and premium unlocks nothing yet.
        """
        code = (payload.code or "").strip().upper()
        now = datetime.now(timezone.utc)

        row = (await db.execute(text("""
            UPDATE coupons
            SET status = 'REDEEMED', redeemed_at = :now,
                customer_id = COALESCE(customer_id, CAST(:cid AS uuid))
            WHERE code = :code
              AND kind = 'PREMIUM_TRIAL'
              AND status = 'ACTIVE'
              AND (customer_id IS NULL OR customer_id = CAST(:cid AS uuid))
              AND (expires_at IS NULL OR expires_at > :now)
            RETURNING trial_days
        """), {"now": now, "code": code, "cid": str(customer.id)})).first()

        if not row:
            raise HTTPException(
                status_code=422, detail="That coupon code is not valid."
            )

        days = int(row[0] or CarevoService.PREMIUM_TRIAL_DAYS)
        # Extend from whichever is later: an unexpired window is added to rather
        # than thrown away, and a lapsed one restarts from today.
        base = customer.premium_until
        if base is not None and base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        start = base if (base is not None and base > now) else now
        new_until = start + timedelta(days=days)

        await db.execute(text(
            "UPDATE customers SET premium_until = :pu WHERE id = :cid"
        ), {"pu": new_until, "cid": str(customer.id)})
        await db.commit()
        await db.refresh(customer)

        return {
            "kind": Coupon.KIND_PREMIUM_TRIAL,
            "premium_until": customer.premium_until,
            "plan": CarevoService._plan_label(customer.premium_until),
            "message": "Premium trial active for {} days.".format(days),
        }

    @staticmethod
    async def check_cart_availability(
        db: AsyncSession, outlet_id: uuid.UUID, item_ids: list
    ) -> dict:
        """Re-check a cart against live menu state, BEFORE payment.

        Exists because an item turned off after it was added stays in the
        already-populated cart, and nothing notices until create_order raises
        409. This endpoint moves that discovery earlier, to a point where the
        customer can still fix it without having paid.

        Still required now that get_menu RETURNS unavailable items rather than
        filtering them out (they render as greyed placeholders). Returning them
        makes the state visible while browsing; it does not make an unavailable
        item orderable, and this gate is what enforces that.

        Read-only and side-effect free: it never mutates the cart or the order.
        create_order remains the authority - this is a courtesy pre-check, not a
        replacement for server-side validation.
        """
        if not item_ids:
            return {"ok": True, "unavailable": []}

        ids = [str(i) for i in item_ids]
        rows = (await db.execute(text("""
            SELECT mi.id, mi.name, mi.is_available, mi.is_active
            FROM menu_items mi
            WHERE mi.id = ANY(:ids)
        """), {"ids": ids})).fetchall()

        found = {str(r.id): r for r in rows}
        unavailable = []
        for iid in ids:
            r = found.get(iid)
            if r is None:
                # Deleted from the menu entirely since it was added.
                unavailable.append({"menu_item_id": iid, "name": None})
            elif not (r.is_available and r.is_active):
                unavailable.append({"menu_item_id": iid, "name": r.name})

        return {"ok": not unavailable, "unavailable": unavailable}

    @staticmethod
    async def list_areas(db: AsyncSession) -> list[dict]:
        """Cities that actually have at least one orderable outlet.

        Derived from live outlet rows, never a hardcoded list: a city appears
        here only while it has >=1 visible, non-deactivated outlet, so picking
        one can never lead to an empty result. When the last outlet in a city is
        hidden or deactivated, the city disappears from the picker on its own.

        `outlets` has no locality/area column today (only `city`), so this
        returns city granularity. See migration 012 (proposed, not applied) for
        the smallest addition that would let this return localities too.
        """
        rows = (await db.execute(text("""
            SELECT city, count(*) AS outlet_count
            FROM outlets
            WHERE is_visible = true
              AND deactivated_at IS NULL
              AND city IS NOT NULL
              AND btrim(city) <> ''
            GROUP BY city
            ORDER BY count(*) DESC, city
        """))).fetchall()
        return [
            {"city": r.city, "outlet_count": int(r.outlet_count)}
            for r in rows
        ]

    @staticmethod
    async def list_active_cities(db: AsyncSession) -> list[dict]:
        """Cities selectable at owner signup (migration 013).

        PUBLIC and unauthenticated, because signup itself is: the dropdown has to
        populate before the owner has an account. Returns only `active` — a
        pending request is not selectable by anyone else until an admin approves
        it, otherwise one owner's typo becomes everyone's option.
        """
        rows = (await db.execute(text(
            "SELECT id, name FROM cities WHERE status = 'active' ORDER BY name"
        ))).fetchall()
        return [{"id": r.id, "name": r.name} for r in rows]
