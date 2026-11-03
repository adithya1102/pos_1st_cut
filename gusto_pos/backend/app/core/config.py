import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Gusto POS API"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # --- CareVo Skip (additive; env-driven with stub-safe defaults) ---
    OTP_STUB_MODE: bool = True
    OTP_STUB_CODE: str = "000000"
    OTP_RATE_LIMIT_PER_HOUR: int = 5
    # Per-IP cap on public owner self-signups (POST /register) per hour.
    REGISTER_RATE_LIMIT_PER_HOUR: int = 5
    # Pickup window: a PAID/live order untouched for this many minutes is
    # auto-abandoned (check-on-read), freeing its pickup_code for reuse.
    PICKUP_TTL_MINUTES: int = 45

    # How long an UNPAID stock reservation is held (migration 033).
    #
    # CHOSEN, NOT INHERITED. This was specified as "the existing payment-retry
    # grace window", and no such window exists in this codebase — verified:
    # COMPLETED_GRACE (30m) governs how long a VERIFIED PICKUP lingers in the
    # owner queue; AppConfig.coldRetryTimeout (60s) is an HTTP retry; a
    # customer_app payment retry reopens the SAME payment session with no
    # expiry of its own; and there is no sweeper for CREATED/PENDING orders at
    # all, since _LIVE_STATUSES is {PAID,RECEIVED,PREPARING,READY}.
    #
    # 600 SECONDS (10 minutes) is the trade-off between two real failures:
    #   * too short — a customer who taps Pay, switches to their UPI app,
    #     authenticates, and switches back loses the units mid-payment and
    #     gets ITEM_SOLD_OUT for food they were in the middle of buying;
    #   * too long  — one abandoned cart holds the last portion of a dish for
    #     that whole duration, and every other customer is told it is gone.
    #
    # Expressed in SECONDS, not minutes, because the value has to be comparable
    # with the gateway's own expiry without a unit conversion in between: the
    # Cashfree order is created with order_expiry_time = now + this, so the
    # payment page dies as close to the hold as the gateway permits.
    #
    # It is NOT an exact match, and the reason is worth knowing before changing
    # this number. Cashfree's live API refuses any expiry inside 15 minutes
    # ("order_expiry_time : Expiry time should be more than 15 min and less
    # than 30 days" — observed as a production 400, and contradicting their
    # payment-lifecycle page, which still says 5 minutes). So the gateway
    # clamps to CashfreeGateway.MIN_ORDER_EXPIRY_SECONDS (960) rather than
    # passing this straight through, and at 600 the clamp is what applies: the
    # payment page outlives the hold by six minutes. Raising this above 960
    # would make the two line up exactly.
    #
    # Lowering this is safe for correctness but not for conversion: a hold that
    # lapses mid-payment is recovered by the late-payment path in mark_paid,
    # which re-acquires the units if they are still there and flags a refund if
    # they are not. Nobody is ever oversold; some customers just get refunded
    # instead of fed.
    STOCK_HOLD_TTL_SECONDS: int = 600

    # STAFF login throttle, shared by /auth/login and /auth/pin-login. Counted
    # per claimed-identifier AND per client IP, over a sliding window.
    #
    # Neither endpoint had any limit, and a staff PIN is 4 digits — 10,000
    # values, exhaustible in minutes against a known username. 10 attempts per
    # 5 minutes is far above anything a human typing their own PIN produces.
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300

    # SQLAlchemy engine echo. Was hardcoded True in core/database.py, which
    # logged every statement WITH its bound parameters — customer phone
    # numbers, pickup codes and token subjects into the platform log stream.
    # Opt-in, so a deploy that sets nothing is quiet.
    SQL_ECHO: bool = False

    # Cap on CONSECUTIVE pickup-code misses per outlet, over a short sliding
    # window. A miss is a code (or order id) that resolves to no order of the
    # caller's own outlet — i.e. lookup-pickup returning found:false and
    # verify-pickup returning 404. Neither lands on an order row, so neither is
    # counted by the per-order 3-strike lockout: that one guards a KNOWN order,
    # this one guards the space of codes around it. A hit resets the counter,
    # so a busy counter with the occasional typo never trips it.
    PICKUP_MISS_LIMIT: int = 10
    PICKUP_MISS_WINDOW_SECONDS: int = 300

    # Per-IP cap on the UNAUTHENTICATED /public/* catalogue reads, per hour.
    # Set far above OTP/REGISTER (5/hr): those guard an action with a cost
    # attached — an SMS, a new organization — while these are cacheable reads
    # of data that is public by definition. The limit exists to blunt scraping
    # and accidental hot loops, not to ration normal use. A busy MCP client
    # listing outlets and then fetching several menus should never see it.
    #
    # 300 -> 1000 because "per IP" is not "per user" for the traffic that
    # actually arrives here. The MCP server is the only caller of /public/* in
    # this repository, and it is a single shared proxy on one Render egress IP,
    # so EVERY connector user's calls land in ONE bucket. The cap is therefore
    # a ceiling on the whole user base at once, not on any individual, and it
    # tightens as adoption grows rather than staying put.
    #
    # This is headroom, not a fix for that shape. Per-user keying would need an
    # identifier the MCP session does not carry, and a client-supplied one is
    # spoofable; neither is worth building without evidence of real contention.
    # An investigation found none — a 40-call burst through the live connector
    # returned 40/40 clean, so the bucket was nowhere near its cap.
    #
    # Note also what this does NOT protect against: the limiter is in-process,
    # so the real ceiling is this number times the worker count, and a restart
    # forgets every bucket.
    PUBLIC_API_RATE_LIMIT_PER_HOUR: int = 1000

    # Master switch for the customer OTP login path. Set false on any publicly
    # reachable deploy while OTP_STUB_MODE is still on, otherwise anyone can mint
    # a customer token for an arbitrary phone number with the stub code.
    CUSTOMER_AUTH_ENABLED: bool = True

    # Default is a NON-GATEWAY sentinel, not "stub".
    #
    # "stub" as the default meant a deploy that simply forgot to set this got
    # working-looking fake payments: orders created, checkout opened, nothing
    # charged. That is exactly what happened on 2026-09-08, and the record of
    # it is 71 payment_transactions rows carrying gateway='razorpay'.
    #
    # get_gateway() still returns the stub for any non-"cashfree" value, so
    # local development is unchanged — set PAYMENT_GATEWAY=stub explicitly and
    # everything behaves as before. The difference is that choosing fake
    # payments is now a deliberate act rather than what you get by omission,
    # and /customer/payment/webhook refuses to run at all unless a LIVE gateway
    # is named (see PaymentGateway.is_live).
    PAYMENT_GATEWAY: str = "unset"
    PAYMENT_GATEWAY_SHAPE: str = "razorpay"

    # ONE reversible server switch: Cashfree prepaid becomes the only payment
    # path. Default false so nothing changes until this is explicitly set.
    # When true, payment_methods_for (carevo_customer/service.py) stops
    # offering PAY_AT_PICKUP/UPI_MANUAL at every outlet, create_order refuses
    # them with a 409, and the owner payment-settings PATCH refuses to turn
    # either on with a 403. Does not delete or rewrite any of that code — it
    # is gated behind this flag so flipping it back to false restores the
    # exact prior behaviour.
    CASHFREE_ONLY: bool = False
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None

    # Cashfree PG. Set PAYMENT_GATEWAY=cashfree to select it; the factory then
    # REFUSES to start an order without these rather than silently serving stub
    # payments. Sandbox by default — production is an explicit opt-in.
    CASHFREE_APP_ID: Optional[str] = None
    CASHFREE_SECRET_KEY: Optional[str] = None
    CASHFREE_ENV: str = "sandbox"            # sandbox | production
    # Public URL Cashfree POSTs webhooks to, e.g.
    # https://gusto-pos-backend.onrender.com/api/v1/customer/payment/webhook
    CASHFREE_NOTIFY_URL: Optional[str] = None

    # Reject an otherwise-validly-signed webhook whose x-webhook-timestamp is
    # older (or newer) than this many seconds versus now. 7200s (2 HOURS), not
    # Cashfree's own suggested 300s: their documented retry schedule spans
    # roughly 42 minutes end to end, and 300s would start rejecting — and
    # therefore permanently losing, since a rejected retry is not re-sent on a
    # shorter cycle — their OWN later retries of a real delivery. Whether
    # x-webhook-timestamp is stamped once per EVENT or re-stamped on every
    # RETRY ATTEMPT is not yet confirmed against the sandbox (see
    # docs/ops/cashfree_only_verify.sql); until it is, this stays generous
    # rather than risking silently dropped real payments.
    CASHFREE_WEBHOOK_MAX_AGE_S: int = 7200

    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_ENABLED: bool = False

    # Google Distance Matrix key for SERVER-SIDE travel ETAs (predict_travel).
    # Distinct from the on-device Android/iOS Maps key: an app-restricted key is
    # rejected for web-service calls, so this must be an unrestricted or
    # IP-restricted key. Empty => predict_travel stays on the haversine fallback
    # (shadow mode), so the feature is inert until this is set on Render.
    MAPS_SERVER_KEY: str = ""

    # --- Push notifications (FCM HTTP v1) -----------------------------------
    # PUSH_ENABLED gates SENDING, exactly as FIREBASE_ENABLED gates the inbound
    # auth path. Sending needs a Firebase SERVICE ACCOUNT — a different and much
    # more privileged credential than google-services.json (which is client-side
    # and only lets a device receive). Point this at the downloaded JSON:
    #
    #   PUSH_ENABLED=true
    #   FCM_SERVICE_ACCOUNT_FILE=/etc/secrets/carevo-fcm.json
    #
    # Left false/empty, every send is recorded as 'skipped' and nothing is
    # transmitted — so the whole pipeline is inert but exercisable until real
    # credentials exist. Never commit the service-account file.
    # --- Outbound email (migration 015) --------------------------------------
    # Gates SENDING of verification / password-reset mail, exactly as
    # PUSH_ENABLED gates FCM. There is no mail transport configured yet, so with
    # this false every send is recorded and logged but nothing leaves the
    # process — the flows are fully exercisable before a provider exists.
    #
    # Owner accounts are NOT Firebase Auth users (username + bcrypt in `users`),
    # so Firebase's built-in verification/reset mail does not apply to them.
    # Reset links are our own single-use tokens; whatever provider is wired in
    # later just has to deliver EmailMessage.body.
    EMAIL_ENABLED: bool = False
    # Base URL the emailed links point at (the app/web page that completes the
    # flow). Left empty until the flows have a real landing page.
    #
    # owner_app does NOT rely on this: it redeems the reset CODE typed into
    # ResetPasswordScreen, so recovery works with this empty. A link is only a
    # convenience for a future web landing page.
    EMAIL_LINK_BASE_URL: str = ""
    EMAIL_FROM: str = "no-reply@carevo.app"

    # --- SMTP transport ------------------------------------------------------
    # The actual wire. Until these were added, EMAIL_ENABLED=true still sent
    # nothing: AccountService._deliver had no transport behind the flag, so
    # every password-reset mail was logged and dropped and forgot-password was
    # a dead end for every owner.
    #
    # Any submission-port SMTP provider works (SES, SendGrid, Mailgun, Gmail
    # app-password). Set on Render as env vars; never commit real credentials.
    #
    #   EMAIL_ENABLED=true
    #   EMAIL_SMTP_HOST=email-smtp.ap-south-1.amazonaws.com
    #   EMAIL_SMTP_PORT=587
    #   EMAIL_SMTP_USER=...
    #   EMAIL_SMTP_PASSWORD=...
    #
    # EMAIL_ENABLED alone is not enough — _deliver also requires a host, and
    # reports "skipped" rather than pretending when one is missing.
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USER: str = ""
    EMAIL_SMTP_PASSWORD: str = ""
    # STARTTLS on the submission port (587) is the default. Set false only for
    # implicit TLS on 465, which uses SMTP_SSL instead.
    EMAIL_SMTP_STARTTLS: bool = True
    # Ceiling on one SMTP conversation. Sized well under the request timeout:
    # a wedged mail server must not hold a password-reset request open.
    EMAIL_SMTP_TIMEOUT_SECONDS: int = 15

    PUSH_ENABLED: bool = False
    FCM_SERVICE_ACCOUNT_FILE: Optional[str] = None

    # --- Menu photo import (OCR) ---------------------------------------------
    # Gates the RapidOCR-backed /pos/menu-import routes, exactly as
    # PUSH_ENABLED gates FCM.
    #
    # OFF BY DEFAULT ON PURPOSE. rapidocr-onnxruntime pulls onnxruntime +
    # OpenCV + numpy: ~124 MB of wheels, ~346 MB installed, and inference holds
    # a few hundred MB of RSS while it runs. That is a serious ask of a 512 MB
    # free-tier instance, so turning this on is a deliberate act with a plan
    # behind it, not a default.
    #
    # The import is LAZY (see menu_ocr.service), so with this false — or with
    # the package simply not installed — the app boots and every other route
    # behaves exactly as before. `ocr_available()` requires BOTH the flag and a
    # working import, and the app asks /pos/menu-import/status before it offers
    # the button.
    OCR_ENABLED: bool = False

    # Shared secret for the local testing dashboard (testing_dashboard module).
    # Every dashboard endpoint requires the X-Testing-Key header to equal this.
    # Empty by default = the dashboard is FAIL-CLOSED (all requests 401) until a
    # real value is set in .env locally and in Render's environment. Never
    # hardcode the real key in source.
    TESTING_DASHBOARD_KEY: str = ""

    # --- Roster-scoped auto-progression (testing only, migration 025 roster) ---
    # Master kill switch. While ON, a TESTER's order (phone on the `testers`
    # roster) auto-advances RECEIVED -> PREPARING -> READY after payment, with a
    # delay between each, and READY then chains into the existing auto-pickup —
    # so a 14-day Play Store test across the roster needs ZERO restaurant-side
    # taps. OFF by default: while false a roster order behaves exactly like a
    # real customer's (staff advance it manually). This is the switch to flip off
    # after the test window. NON-roster orders are never touched at any value.
    AUTO_ADVANCE_ROSTER_ORDERS: bool = False
    # The single gap, in seconds, before each automatic stage. One knob, easy to
    # tune. 20s reads as a plausible kitchen cadence to a watching tester.
    AUTO_ADVANCE_DELAY_SECONDS: int = 20
    # How often the durable poller checks for due steps. Small so a step fires
    # close to its due time; the real gap between stages is AUTO_ADVANCE_DELAY_SECONDS
    # (enforced by each row's due_at), this only bounds the polling lag on top.
    AUTO_ADVANCE_POLL_SECONDS: int = 5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()


class PaymentConfigError(RuntimeError):
    """Raised at startup when CASHFREE_ONLY cannot be safely satisfied.

    Deliberately not swallowed anywhere — letting this propagate out of the
    FastAPI startup event is what makes the process refuse to start, rather
    than booting into a state where CASHFREE_ONLY=true silently keeps
    accepting pay-at-pickup/UPI (because the resolver falls back to "no
    gateway, no methods") or routes webhooks nobody can ever authenticate.
    """


# The ONE shared definition of "this is not a production deploy", read off
# APP_ENV. Used by app/main.py (to gate /docs) and by
# validate_gateway_startup_posture below (to gate the fail-closed stub-gateway
# check); both used to carry their own separate copy of this set, which is how
# the two could silently drift apart.
NON_PRODUCTION_ENVS = {"dev", "development", "local", "test"}

def normalize_payment_gateway(value: Optional[str]) -> str:
    """The ONE normalization for comparing PAYMENT_GATEWAY against the known
    literals ("cashfree", "stub"). Strips surrounding whitespace and
    lowercases.

    Before this, three call sites each did their own version of this —
    validate_cashfree_only_config and validate_gateway_startup_posture (both
    below) did `.strip().lower()`, while get_gateway()
    (carevo_payments/gateway.py) and _gateway_can_charge()
    (carevo_customer/service.py) did `.lower()` only, with NO strip. The
    result: PAYMENT_GATEWAY=" cashfree" (one leading space) passed
    validate_gateway_startup_posture's check (believed to be cashfree) while
    get_gateway() and _gateway_can_charge() resolved it to the STUB — a
    deploy that believes it is correctly configured and is actually not
    charging anyone through a real gateway. Independent verification
    confirmed this live. One helper, used everywhere PAYMENT_GATEWAY is
    compared against "cashfree" or "stub", closes that gap by construction.
    """
    return (value or "").strip().lower()


# The literal signal used to tell a test run from a real one. Same variable
# and same convention as main.py's _DOCS_ENABLED (APP_ENV, default
# "production" so an unconfigured deploy is treated as real) — but narrower:
# only the literal value "test" exempts THIS check, not "dev"/"local", since
# those are real processes that should still fail loudly if a CASHFREE_ONLY
# deploy is half-built. Deliberately NOT the same set as NON_PRODUCTION_ENVS:
# that set answers "is this a real deploy worth enforcing fail-closed posture
# on", this one answers only "is this the test harness".
# tests/conftest.py sets APP_ENV=test before the app is ever imported.
_TEST_APP_ENV = "test"


def validate_cashfree_only_config(cfg: "Settings" = None, *,
                                  env_name: Optional[str] = None) -> None:
    """Fail closed: CASHFREE_ONLY=true must never run with a half-built
    Cashfree setup. Checked once at process startup (app/main.py), never
    per-request — a misconfiguration here is not something a request should
    ever be allowed to observe.

    Raises PaymentConfigError naming the offending VARIABLE, never its value
    (a credential value must never appear in a startup log line).

    No-op when:
      * `env_name` (default: the live APP_ENV) is the literal test marker, or
      * CASHFREE_ONLY is false — the switch nothing has turned on yet, so
        there is nothing to enforce.
    """
    cfg = cfg if cfg is not None else settings
    if env_name is None:
        env_name = os.getenv("APP_ENV", "production").strip().lower()
    if env_name == _TEST_APP_ENV:
        return
    if not cfg.CASHFREE_ONLY:
        return

    if normalize_payment_gateway(cfg.PAYMENT_GATEWAY) != "cashfree":
        raise PaymentConfigError(
            "CASHFREE_ONLY=true requires PAYMENT_GATEWAY=cashfree; the "
            "variable PAYMENT_GATEWAY is not set to cashfree"
        )

    missing = [name for name in ("CASHFREE_APP_ID", "CASHFREE_SECRET_KEY")
               if not getattr(cfg, name, None)]
    if missing:
        raise PaymentConfigError(
            "CASHFREE_ONLY=true but required Cashfree credential "
            f"variable(s) are not set: {', '.join(missing)}"
        )


def validate_gateway_startup_posture(cfg: "Settings" = None, *,
                                      env_name: Optional[str] = None,
                                      allow_stub: Optional[str] = None) -> None:
    """Fail closed on ANY deploy — not just a CASHFREE_ONLY one.

    A non-cashfree PAYMENT_GATEWAY (the "unset" default included: that is
    exactly what shipped fake payments on 2026-09-08) must never run outside
    NON_PRODUCTION_ENVS unless an operator has explicitly opted in with
    ALLOW_STUB_GATEWAY=true. Checked once at process startup
    (app/main.py's on_startup), alongside — and independently of —
    validate_cashfree_only_config: this one applies whether CASHFREE_ONLY is
    true or false.

    Raises PaymentConfigError naming the offending VARIABLE (PAYMENT_GATEWAY).
    """
    cfg = cfg if cfg is not None else settings
    if env_name is None:
        env_name = os.getenv("APP_ENV", "production").strip().lower()
    if env_name in NON_PRODUCTION_ENVS:
        return

    if normalize_payment_gateway(cfg.PAYMENT_GATEWAY) == "cashfree":
        return

    if allow_stub is None:
        allow_stub = os.getenv("ALLOW_STUB_GATEWAY", "")
    if allow_stub.strip().lower() == "true":
        return

    raise PaymentConfigError(
        "PAYMENT_GATEWAY is not cashfree outside a non-production "
        "environment (APP_ENV is not one of "
        f"{sorted(NON_PRODUCTION_ENVS)}); set PAYMENT_GATEWAY=cashfree or "
        "ALLOW_STUB_GATEWAY=true to run a stub gateway here. The variable "
        "PAYMENT_GATEWAY is the one that must change"
    )