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
from datetime import datetime, timedelta, timezone
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

    #: Is this a REAL money path whose webhooks may be trusted at all?
    #:
    #: The stub is not. It exists so the customer flow is walkable without
    #: credentials, which means nothing it receives on a webhook proves a
    #: payment happened — there is no counterparty to have signed it. An
    #: endpoint that flips orders to PAID is only as trustworthy as the thing
    #: vouching for the request, so a non-live gateway must not be given one.
    #:
    #: Read by /customer/payment/webhook, which 503s rather than parsing a body
    #: it has no way to authenticate. /customer/payment/simulate is unaffected:
    #: it is customer-authenticated, stub-only, and never pretends otherwise.
    is_live: bool = False

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


# --------------------------- gateway failures -------------------------------
# Every one of these used to be a bare `RuntimeError`, which the create-order
# call site could only catch as one undifferentiated blob — so the three very
# different conditions below (we are misconfigured / the customer's order
# cannot be expressed / the provider is having a bad day) could not be turned
# into three different answers for the customer. They all became a naked 500.
#
# All THREE still subclass RuntimeError. That is deliberate: any caller already
# written as `except RuntimeError` keeps behaving exactly as it did, so this is
# additive rather than a change every call site has to be updated for.
class GatewayError(RuntimeError):
    """Base: the payment gateway could not produce an order."""


class GatewayConfigError(GatewayError):
    """The gateway is selected but this deployment cannot use it.

    Our configuration, not the provider's fault and not the customer's. Nothing
    about retrying changes the answer until an operator sets the credentials,
    which is why the caller maps this to 503 rather than 502.
    """


class GatewayRequestError(GatewayError):
    """The order cannot be expressed as a request this gateway will accept.

    Raised BEFORE the network call, from a constraint we can check ourselves
    against the provider's published contract. Carries a stable `code` and a
    `customer_message`, because the caller has to say something true to the
    person standing in the app — "payments are down" would be a lie.
    """

    def __init__(self, message: str, *, code: str, customer_message: str):
        super().__init__(message)
        self.code = code
        self.customer_message = customer_message


class GatewayUpstreamError(GatewayError):
    """The provider refused, timed out, or answered with something unusable.

    `status_code` and `body` are the provider's own, carried so the caller can
    log WHY without re-reading the response. Credentials are never in either —
    they travel in request headers and Cashfree does not echo them.
    """

    def __init__(self, message: str, *, status_code: Optional[int] = None,
                 body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ASCII only, spelled out rather than using str.isalnum(): 'é' and '٣' are both
# alphanumeric to Python and neither is alphanumeric to a payment gateway.
_ASCII_ALNUM = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_ASCII_DIGITS = frozenset("0123456789")


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
        """FAILS CLOSED, exactly like CashfreeGateway's verifier.

        This used to `return True` when no webhook secret was configured — and
        RAZORPAY_WEBHOOK_SECRET is unset on every deploy that has not
        deliberately set it. Combined with parse_webhook resolving outcome=PAID
        from the mere presence of an `order_id`, that made
        POST /customer/payment/webhook {"order_id": "<own order>"} a free-money
        endpoint reachable by anyone, with no credential and no signature.

        Absent config now denies rather than admits. A webhook that cannot be
        authenticated is not a payment, and guessing otherwise is the one
        mistake in this file that moves money.
        """
        if not self.webhook_secret or not signature:
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
    is_live = True
    API_VERSION = "2023-08-01"
    SANDBOX_BASE = "https://sandbox.cashfree.com/pg"
    PROD_BASE = "https://api.cashfree.com/pg"

    # Cashfree's own floor for order_expiry_time, VERIFIED against their docs
    # rather than assumed: "Set order expiry time: Minimum 5 minutes, maximum
    # 30 days" — cashfree.com/docs/payments/online/resources/payment-lifecycle.
    # (The Create Order API reference itself documents the field but states no
    # bound, so the lifecycle page is the citation.)
    #
    # The expiry is clamped to this rather than passed straight through: a
    # STOCK_HOLD_TTL_SECONDS below 300 is a legitimate thing to set for local
    # testing, and letting it reach Cashfree would turn every checkout into a
    # hard create-order failure. Clamping degrades to "the gateway outlives the
    # hold", which is exactly the case mark_paid's late-payment path already
    # handles.
    MIN_ORDER_EXPIRY_SECONDS = 300

    # Cashfree's documented floor for order_amount: "minimum: 1", i.e. one
    # rupee. Checked HERE rather than discovered as a 400 from the wire,
    # because this is reachable from a perfectly ordinary customer action: a
    # points coupon or a 100%-off promotion whose discount meets the basket
    # total settles at ₹0 (service.create_order clamps with max(..., 0.0)),
    # and ₹0 is not an amount Cashfree will take.
    MIN_ORDER_AMOUNT = 1.00

    # customer_details.customer_id — "A unique identifier for the customer.
    # Use alphanumeric values only." minLength 3, maxLength 50.
    CUSTOMER_ID_MIN = 3
    CUSTOMER_ID_MAX = 50

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

    @classmethod
    def expiry_seconds(cls) -> int:
        """The gateway expiry actually sent, after clamping to Cashfree's floor.

        Separated from the timestamp so it can be asserted on directly: the
        interesting property is "this equals the hold TTL unless the TTL is
        below Cashfree's minimum", and that is awkward to test through a
        formatted string.
        """
        return max(int(settings.STOCK_HOLD_TTL_SECONDS),
                   cls.MIN_ORDER_EXPIRY_SECONDS)

    @classmethod
    def _expiry_iso(cls) -> str:
        """now + expiry_seconds(), as an offset-aware ISO 8601 string.

        `timespec="seconds"` because Cashfree's parser rejects microseconds.
        """
        at = datetime.now(timezone.utc) + timedelta(seconds=cls.expiry_seconds())
        return at.isoformat(timespec="seconds")

    @classmethod
    def _customer_id(cls, raw: Any) -> str:
        """`customer_details.customer_id`, reduced to what Cashfree documents.

        We pass `customers.id`, a UUID — and a UUID's canonical spelling
        carries four hyphens. Cashfree's Create Order reference says of this
        field "Use alphanumeric values only" (minLength 3, maxLength 50) while
        their SDK docs describe hyphens as allowed, so which spelling is
        accepted depends on which of the two is authoritative.

        Stripping the hyphens costs nothing and is valid under BOTH readings,
        which is the point: a field whose acceptance depends on resolving a
        documentation conflict has no business on the one request standing
        between a customer and paying. The 32 hex characters that remain are
        still unique and still the same customer, and nothing reads this value
        back — the webhook correlates on `order_id` (see parse_webhook).
        """
        cleaned = "".join(ch for ch in str(raw or "") if ch in _ASCII_ALNUM)
        if len(cleaned) < cls.CUSTOMER_ID_MIN:
            return "guest"
        return cleaned[:cls.CUSTOMER_ID_MAX]

    @staticmethod
    def _customer_phone(raw: Any) -> str:
        """`customer_details.customer_phone`, in a shape Cashfree documents.

        Their troubleshooting page lists three valid spellings — a bare
        10-digit Indian number (9090407368), the same with its country code
        and a plus (+919090407368), and any international number prefixed with
        a plus — and one error, `customer_phone_invalid`, for everything else.
        The schema's maxLength of 10 is overridden by the leading '+'.

        What arrives here is not reliably one of those three. A Firebase
        phone sign-in stores E.164 (`+919876543210`, already fine), a Google
        sign-in stores no phone at all, and rows predating Firebase hold
        whatever the old stub flow was given — including separators. So this
        reduces each of those to a documented spelling rather than trusting
        the column. A bare country-coded number gains the '+' it needs to
        escape the 10-digit limit; anything too short to be a phone number
        falls back to the placeholder, exactly as a missing one does.
        """
        text_ = str(raw or "").strip()
        digits = "".join(ch for ch in text_ if ch in _ASCII_DIGITS)
        if len(digits) < 10:
            # Includes the empty case: a Google-only customer has no phone on
            # file, and Cashfree requires the field.
            return "9999999999"
        if len(digits) == 10 and not text_.startswith("+"):
            return digits
        return f"+{digits}"

    async def create_order(self, amount_rupees: float, currency: str = "INR",
                           receipt: Optional[str] = None,
                           customer: Optional[Mapping[str, Any]] = None) -> GatewayOrder:
        if not self.configured:
            raise GatewayConfigError(
                "Cashfree is selected but CASHFREE_APP_ID / CASHFREE_SECRET_KEY "
                "are not set. Refusing to fall back to the stub — a silent "
                "downgrade to fake payments is worse than a hard failure."
            )

        amount = round(float(amount_rupees), 2)
        if amount < self.MIN_ORDER_AMOUNT:
            raise GatewayRequestError(
                f"order_amount {amount} is below Cashfree's documented "
                f"minimum of {self.MIN_ORDER_AMOUNT}",
                code="AMOUNT_BELOW_GATEWAY_MINIMUM",
                customer_message=(
                    "This order comes to ₹0 after your discount, and payments "
                    "cannot be taken for ₹0. Remove the discount to place it, "
                    "or add something to your order."
                ),
            )

        cust = dict(customer or {})
        body = {
            # OUR order id, so the webhook needs no correlation table.
            "order_id": str(receipt),
            # Rupees, not paise. Cashfree rejects integer paise here.
            "order_amount": amount,
            "order_currency": currency,
            "customer_details": {
                "customer_id": self._customer_id(cust.get("id")),
                # Cashfree requires a phone; sandbox accepts this placeholder for
                # customers who signed in with Google and have none on file.
                "customer_phone": self._customer_phone(cust.get("phone")),
                **({"customer_email": cust["email"]} if cust.get("email") else {}),
                **({"customer_name": cust["name"]} if cust.get("name") else {}),
            },
            "order_meta": {
                **({"notify_url": settings.CASHFREE_NOTIFY_URL}
                   if settings.CASHFREE_NOTIFY_URL else {}),
            },
            # Die at the same moment the stock hold does (migration 033).
            #
            # Without this the gateway order outlived the reservation, so a
            # customer could sit on a live payment page long after their units
            # had been swept back into stock, pay, and land in the
            # re-acquire-or-refund path for no reason other than a clock
            # mismatch. Matching the two means the common case is a payment
            # page that is already dead, which is a plain "this order expired"
            # instead of a successful charge followed by a refund.
            #
            # ISO 8601 WITH an offset — Cashfree rejects a naive timestamp.
            "order_expiry_time": self._expiry_iso(),
        }

        # DNS, TLS, connect refusals and timeouts all surface as httpx errors.
        # Translated here so the whole failure surface of this method is one
        # exception family and the caller needs no knowledge of our HTTP
        # client — the alternative is every call site importing httpx to catch
        # what the gateway does internally.
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.post(f"{self.base_url}/orders",
                                        headers=self._headers(), json=body)
        except httpx.HTTPError as exc:
            raise GatewayUpstreamError(
                f"Cashfree is unreachable: {type(exc).__name__}: {exc}"
            ) from exc

        if res.status_code >= 400:
            raise GatewayUpstreamError(
                f"Cashfree create-order failed ({res.status_code})",
                status_code=res.status_code,
                # Cashfree's own error JSON names the offending field, which is
                # the single most useful thing in the log. It is their response
                # body, so it cannot contain our credentials.
                body=res.text[:500],
            )

        # A 2xx carrying HTML — a proxy error page, a captive portal — would
        # otherwise raise a bare ValueError out of this method.
        try:
            data = res.json()
        except ValueError as exc:
            raise GatewayUpstreamError(
                "Cashfree returned a non-JSON body on a 2xx",
                status_code=res.status_code, body=res.text[:500],
            ) from exc
        if not isinstance(data, dict):
            raise GatewayUpstreamError(
                f"Cashfree returned {type(data).__name__}, expected an object",
                status_code=res.status_code, body=res.text[:500],
            )

        session = data.get("payment_session_id")
        if not session:
            raise GatewayUpstreamError(
                "Cashfree returned no payment_session_id",
                status_code=res.status_code, body=res.text[:500],
            )

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
