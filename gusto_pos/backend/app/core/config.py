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
    # 15 minutes is the trade-off between two real failures:
    #   * too short — a customer who taps Pay, switches to their UPI app,
    #     authenticates, and switches back loses the units mid-payment and
    #     gets ITEM_SOLD_OUT for food they were in the middle of buying;
    #   * too long  — one abandoned cart holds the last portion of a dish for
    #     that whole duration, and every other customer is told it is gone.
    # It also sits inside Cashfree's own payment-session validity, so a session
    # that is still usable is never backed by a reservation that has lapsed.
    STOCK_RESERVATION_TTL_MINUTES: int = 15

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