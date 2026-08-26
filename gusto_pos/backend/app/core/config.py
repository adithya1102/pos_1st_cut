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

    # Cap on CONSECUTIVE pickup-code misses per outlet, over a short sliding
    # window. A miss is a code (or order id) that resolves to no order of the
    # caller's own outlet — i.e. lookup-pickup returning found:false and
    # verify-pickup returning 404. Neither lands on an order row, so neither is
    # counted by the per-order 3-strike lockout: that one guards a KNOWN order,
    # this one guards the space of codes around it. A hit resets the counter,
    # so a busy counter with the occasional typo never trips it.
    PICKUP_MISS_LIMIT: int = 10
    PICKUP_MISS_WINDOW_SECONDS: int = 300

    # Master switch for the customer OTP login path. Set false on any publicly
    # reachable deploy while OTP_STUB_MODE is still on, otherwise anyone can mint
    # a customer token for an arbitrary phone number with the stub code.
    CUSTOMER_AUTH_ENABLED: bool = True

    PAYMENT_GATEWAY: str = "stub"
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
    EMAIL_LINK_BASE_URL: str = ""
    EMAIL_FROM: str = "no-reply@carevo.app"

    PUSH_ENABLED: bool = False
    FCM_SERVICE_ACCOUNT_FILE: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()