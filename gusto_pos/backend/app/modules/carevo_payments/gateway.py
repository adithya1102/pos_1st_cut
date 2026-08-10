"""
CareVo Skip — payment gateway abstraction.

Env-driven. No hardcoded keys. A `StubRazorpayGateway` produces razorpay-shaped
ids so the whole customer flow is walkable without real credentials, while the
same interface can later be backed by a real Razorpay client.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import httpx

from app.core.config import settings


@dataclass
class GatewayOrder:
    gateway: str
    gateway_order_id: str
    amount: int          # minor units (paise)
    currency: str
    key_id: Optional[str]
    # Cashfree's hosted checkout is opened with this, not with an order id.
    # Optional because Razorpay has no equivalent — it opens on order_id + key_id.
    # ADDITIVE: every existing reader of GatewayOrder is unaffected.
    payment_session_id: Optional[str] = None


@dataclass
class WebhookEvent:
    """One gateway webhook, normalised.

    Exists so the /payment/webhook endpoint contains ZERO gateway-specific
    parsing. Razorpay nests the payment under payload.payment.entity; Cashfree
    puts it under data.payment with a different status vocabulary. Without this,
    adding Cashfree would mean an if/else in the controller, and ZohoPay later
    would mean a third branch.
    """

    # PAID | FAILED | PENDING | UNKNOWN — the only vocabulary the caller sees.
    outcome: str
    gateway_order_id: Optional[str] = None
    gateway_payment_id: Optional[str] = None
    # The id WE generated (customer_orders.id). Cashfree echoes it back as
    # order_id because we supply it on create; Razorpay does not.
    our_order_id: Optional[str] = None
    method: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(ABC):
    """Interface every gateway implementation must satisfy."""

    name: str = "base"

    @abstractmethod
    async def create_order(self, amount_rupees: float, currency: str = "INR",
                           receipt: Optional[str] = None,
                           customer: Optional[Mapping[str, Any]] = None) -> GatewayOrder:
        """ASYNC because a real gateway is a network call.

        The stub is instant, but Cashfree's Create Order is an HTTPS round trip;
        running that synchronously inside the async request handler would block
        the whole event loop for its duration.
        """
        ...

    @abstractmethod
    def verify_webhook_signature(self, body: bytes, signature: Optional[str],
                                 *, timestamp: Optional[str] = None) -> bool:
        """`timestamp` is keyword-only and optional so Razorpay's two-argument
        call site keeps working; Cashfree signs timestamp+body and needs it."""
        ...

    @abstractmethod
    def parse_webhook(self, body: bytes, payload: dict) -> WebhookEvent:
        ...

    @abstractmethod
    def make_payment_id(self) -> str:
        ...

    @abstractmethod
    def sign_payment(self, gateway_order_id: str, gateway_payment_id: str) -> Optional[str]:
        ...


def _rand(prefix: str, nbytes: int = 12) -> str:
    return f"{prefix}_{secrets.token_hex(nbytes)}"


class StubRazorpayGateway(PaymentGateway):
    """Razorpay-shaped stub. Signatures are real HMAC-SHA256 when a secret is set."""

    name = "razorpay"

    def __init__(self):
        self.key_id = settings.RAZORPAY_KEY_ID or "rzp_test_stub"
        self.key_secret = settings.RAZORPAY_KEY_SECRET
        self.webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET

    async def create_order(self, amount_rupees: float, currency: str = "INR",
                           receipt: Optional[str] = None,
                           customer: Optional[Mapping[str, Any]] = None) -> GatewayOrder:
        return GatewayOrder(
            gateway=self.name,
            gateway_order_id=_rand("order"),
            amount=int(round(float(amount_rupees) * 100)),
            currency=currency,
            key_id=self.key_id,
        )

    def make_payment_id(self) -> str:
        return _rand("pay")

    def sign_payment(self, gateway_order_id: str, gateway_payment_id: str) -> Optional[str]:
        """Razorpay checkout signature = HMAC_SHA256(order_id|payment_id, key_secret)."""
        if not self.key_secret:
            return None
        msg = f"{gateway_order_id}|{gateway_payment_id}".encode()
        return hmac.new(self.key_secret.encode(), msg, hashlib.sha256).hexdigest()

    def verify_webhook_signature(self, body: bytes, signature: Optional[str],
                                 *, timestamp: Optional[str] = None) -> bool:
        # Stub mode: if no webhook secret configured, accept everything.
        if not self.webhook_secret:
            return True
        if not signature:
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, body: bytes, payload: dict) -> WebhookEvent:
        """Razorpay shape: payload.payment.entity, with a flat-dict fallback for
        the hand-rolled bodies /payment/simulate and the older tests send."""
        entity = {}
        if isinstance(payload.get("payload"), dict):
            entity = payload["payload"].get("payment", {}).get("entity", {}) or {}
        event = (payload.get("event") or "").lower()
        captured = entity.get("status") in ("captured", "authorized")
        return WebhookEvent(
            # Absent an explicit failure marker this stays PAID, which is the
            # behaviour the endpoint had before normalisation existed.
            outcome="FAILED" if ("failed" in event or entity.get("status") == "failed")
            else "PAID" if (captured or entity or payload.get("gateway_payment_id")
                            or payload.get("order_id")) else "UNKNOWN",
            gateway_order_id=entity.get("order_id") or payload.get("gateway_order_id"),
            gateway_payment_id=entity.get("id") or payload.get("gateway_payment_id"),
            our_order_id=payload.get("order_id") or payload.get("customer_order_id"),
            method=entity.get("method") or payload.get("method"),
            raw=payload,
        )


class CashfreeGateway(PaymentGateway):
    """Cashfree PG (API version 2023-08-01).

    Sandbox vs production is the BASE URL only — same code, same credentials
    shape. Credentials come from env (CASHFREE_APP_ID / CASHFREE_SECRET_KEY);
    nothing is hardcoded and nothing is committed.

    Differences from Razorpay that the abstraction has to absorb:
      * checkout opens on `payment_session_id`, not order_id + key_id;
      * `order_id` is supplied BY US on create and echoed back on the webhook,
        so the webhook can find our order directly without a lookup table;
      * the webhook signs `timestamp + rawBody` and sends base64, where
        Razorpay signs the body alone and sends hex;
      * amounts are decimal RUPEES on the wire, not paise.
    """

    name = "cashfree"
    API_VERSION = "2023-08-01"
    SANDBOX_BASE = "https://sandbox.cashfree.com/pg"
    PROD_BASE = "https://api.cashfree.com/pg"

    def __init__(self):
        self.app_id = settings.CASHFREE_APP_ID
        self.secret_key = settings.CASHFREE_SECRET_KEY
        # Default sandbox. Flipping to production is a deliberate env change,
        # never a default — a mistake here moves real money.
        self.base_url = (
            self.PROD_BASE if (settings.CASHFREE_ENV or "sandbox").lower() == "production"
            else self.SANDBOX_BASE
        )

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.secret_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-client-id": self.app_id or "",
            "x-client-secret": self.secret_key or "",
            "x-api-version": self.API_VERSION,
            "Content-Type": "application/json",
        }

    async def create_order(self, amount_rupees: float, currency: str = "INR",
                           receipt: Optional[str] = None,
                           customer: Optional[Mapping[str, Any]] = None) -> GatewayOrder:
        if not self.configured:
            raise RuntimeError(
                "Cashfree is selected but CASHFREE_APP_ID / CASHFREE_SECRET_KEY "
                "are not set. Refusing to fall back to the stub — a silent "
                "downgrade to fake payments is worse than a hard failure."
            )

        cust = dict(customer or {})
        body = {
            # OUR order id, so the webhook needs no correlation table.
            "order_id": str(receipt),
            # Rupees, not paise. Cashfree rejects integer paise here.
            "order_amount": round(float(amount_rupees), 2),
            "order_currency": currency,
            "customer_details": {
                "customer_id": str(cust.get("id") or "guest"),
                # Cashfree requires a phone; sandbox accepts this placeholder for
                # customers who signed in with Google and have none on file.
                "customer_phone": str(cust.get("phone") or "9999999999"),
                **({"customer_email": cust["email"]} if cust.get("email") else {}),
                **({"customer_name": cust["name"]} if cust.get("name") else {}),
            },
            "order_meta": {
                **({"notify_url": settings.CASHFREE_NOTIFY_URL}
                   if settings.CASHFREE_NOTIFY_URL else {}),
            },
        }

        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(f"{self.base_url}/orders",
                                    headers=self._headers(), json=body)
        if res.status_code >= 400:
            raise RuntimeError(
                f"Cashfree create-order failed ({res.status_code}): {res.text[:300]}"
            )
        data = res.json()

        session = data.get("payment_session_id")
        if not session:
            raise RuntimeError("Cashfree returned no payment_session_id")

        return GatewayOrder(
            gateway=self.name,
            # Cashfree's own id, kept as the gateway-side reference.
            gateway_order_id=str(data.get("cf_order_id") or data.get("order_id") or receipt),
            amount=int(round(float(data.get("order_amount", amount_rupees)) * 100)),
            currency=str(data.get("order_currency") or currency),
            key_id=self.app_id,
            payment_session_id=str(session),
        )

    def verify_webhook_signature(self, body: bytes, signature: Optional[str],
                                 *, timestamp: Optional[str] = None) -> bool:
        """Cashfree: base64( HMAC_SHA256( timestamp + rawBody, secret_key ) ).

        Note what this does NOT do: fall back to "accept everything" when the
        secret is missing, the way the stub does. An unverifiable webhook that
        flips orders to PAID is a free-money endpoint, so absent config fails
        CLOSED.

        The raw body must be the exact bytes received — re-serialising the JSON
        changes key order and whitespace and breaks the digest.
        """
        if not self.secret_key or not signature or not timestamp:
            return False
        signed = f"{timestamp}{body.decode('utf-8', 'replace')}".encode()
        expected = base64.b64encode(
            hmac.new(self.secret_key.encode(), signed, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(expected, signature)

    # Cashfree's own status vocabulary -> ours. Anything unlisted stays UNKNOWN
    # so a new status can never be silently read as success.
    _OUTCOME = {
        "SUCCESS": "PAID",
        "FAILED": "FAILED",
        "USER_DROPPED": "FAILED",
        "CANCELLED": "FAILED",
        "PENDING": "PENDING",
        "NOT_ATTEMPTED": "PENDING",
        "FLAGGED": "PENDING",
    }

    def parse_webhook(self, body: bytes, payload: dict) -> WebhookEvent:
        data = payload.get("data") or {}
        payment = data.get("payment") or {}
        order = data.get("order") or {}

        status = str(payment.get("payment_status") or "").upper()
        outcome = self._OUTCOME.get(status, "UNKNOWN")
        # The event type is the cross-check: a SUCCESS status inside a
        # PAYMENT_FAILED_WEBHOOK is not a payment, it is a bug or an attack.
        etype = str(payload.get("type") or "").upper()
        if "FAILED" in etype or "DROPPED" in etype:
            outcome = "FAILED"

        pm = payment.get("payment_method")
        if isinstance(pm, dict) and pm:
            method = next(iter(pm.keys()))     # {"upi": {...}} -> "upi"
        else:
            method = payment.get("payment_group") or None

        return WebhookEvent(
            outcome=outcome,
            gateway_order_id=str(order.get("order_id")) if order.get("order_id") else None,
            gateway_payment_id=(str(payment["cf_payment_id"])
                                if payment.get("cf_payment_id") else None),
            # We set order_id = customer_orders.id on create, so this IS our id.
            our_order_id=str(order.get("order_id")) if order.get("order_id") else None,
            method=method,
            raw=payload,
        )

    def make_payment_id(self) -> str:
        return _rand("cfpay")

    def sign_payment(self, gateway_order_id: str, gateway_payment_id: str) -> Optional[str]:
        """No client-side checkout signature in Cashfree's model — the webhook
        signature is the authority. Returning None is correct, not a stub."""
        return None


def get_gateway() -> PaymentGateway:
    """Factory. PAYMENT_GATEWAY is the real selector.

    PAYMENT_GATEWAY_SHAPE is retained only as a legacy alias for the stub's
    wire shape. Before this, the factory read SHAPE while /payment/simulate
    read PAYMENT_GATEWAY — two settings for one decision, which is how you end
    up with a "real gateway" deploy still serving stub orders.
    """
    selected = (settings.PAYMENT_GATEWAY or "stub").lower()
    if selected == "cashfree":
        return CashfreeGateway()
    return StubRazorpayGateway()
