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

    # Master switch for the customer OTP login path. Set false on any publicly
    # reachable deploy while OTP_STUB_MODE is still on, otherwise anyone can mint
    # a customer token for an arbitrary phone number with the stub code.
    CUSTOMER_AUTH_ENABLED: bool = True

    PAYMENT_GATEWAY: str = "stub"
    PAYMENT_GATEWAY_SHAPE: str = "razorpay"
    RAZORPAY_KEY_ID: Optional[str] = None
    RAZORPAY_KEY_SECRET: Optional[str] = None
    RAZORPAY_WEBHOOK_SECRET: Optional[str] = None

    FIREBASE_PROJECT_ID: Optional[str] = None
    FIREBASE_ENABLED: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()