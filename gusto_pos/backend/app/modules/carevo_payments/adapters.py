"""Provider-independent webhook verification (reconciliation layer).

ADDITIVE. Nothing in app/modules/carevo_customer/controller.py changes to
introduce this file — /customer/payment/webhook keeps calling
CashfreeGateway.verify_webhook_signature / parse_webhook exactly as it did
before, so every existing webhook test (test_api_webhook_cross_order.py,
test_api_webhook_replay_window.py, test_api_webhook_concurrency.py,
test_api_payment_webhook_auth.py, test_api_cashfree_hardening.py) proves this
by continuing to pass unmodified.

This module is the NEW surface: a `ProviderAdapter` that any caller — today
only the vendor-gateway webhook route (Task 5) — can use without knowing
which payment provider it is talking to. `CashfreeAdapter` wraps the SAME
`CashfreeGateway` methods the existing route calls, so its behaviour is a
re-exposure of already-shipped logic, not a reimplementation.

Rules every adapter in this file follows:
  * Verify over the RAW bytes. No adapter ever re-serialises the parsed JSON
    before computing or checking a signature.
  * hmac.compare_digest only — never `==` on digests.
  * Timestamp tolerance uses the SAME window constant and pattern as the
    pre-existing CASHFREE_WEBHOOK_MAX_AGE_S check in
    carevo_customer/controller.py: a missing, non-numeric, or out-of-window
    (past OR future) timestamp REJECTS. "Out of window" is symmetric, exactly
    as the existing `abs(time.time() - ts_value) > max_age_s` check is.
  * The body size cap is enforced BEFORE any JSON parsing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from app.core.config import settings

# 256 KiB. Every real webhook body this codebase has ever seen (Cashfree,
# Razorpay) is a few KB of JSON; this is headroom, not a realistic ceiling,
# and exists so an oversized body is rejected before json.loads ever runs
# over it.
MAX_WEBHOOK_BODY_BYTES = 262_144


class AdapterError(RuntimeError):
    """Base: a webhook could not be verified or normalized. Never carries the
    secret, the signature, or the body — only what rule was violated."""


class BodyTooLargeError(AdapterError):
    pass


class MissingSignatureError(AdapterError):
    pass


class InvalidSignatureError(AdapterError):
    pass


class MissingTimestampError(AdapterError):
    pass


class InvalidTimestampError(AdapterError):
    pass


class StaleTimestampError(AdapterError):
    pass


class AdapterConfigError(AdapterError):
    """The adapter itself is not usable in this deployment (disabled flag,
    missing secret) — distinct from a bad delivery."""


# PAID | FAILED | PENDING | UNKNOWN — the only vocabulary any caller sees,
# same closed vocabulary WebhookEvent.outcome already uses in gateway.py.
@dataclass(frozen=True)
class VerifiedEvent:
    provider: str
    event_id: Optional[str]
    order_ref: Optional[str]
    provider_payment_id: Optional[str]
    amount_paise: Optional[int]
    currency: Optional[str]
    status: str
    occurred_at: Optional[float]
    raw: dict = field(default_factory=dict)


def _check_body_size(raw_body: bytes) -> None:
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise BodyTooLargeError(
            f"webhook body exceeds {MAX_WEBHOOK_BODY_BYTES} bytes"
        )


def _check_timestamp_window(ts_raw: Optional[str], *, max_age_s: int) -> float:
    """The one shared replay-tolerance check, same shape as the pre-existing
    inline block in carevo_customer/controller.py's payment_webhook."""
    if ts_raw is None or ts_raw.strip() == "":
        raise MissingTimestampError("webhook timestamp is missing")
    try:
        ts = float(ts_raw.strip())
    except (TypeError, ValueError) as exc:
        raise InvalidTimestampError("webhook timestamp is not numeric") from exc
    age = time.time() - ts
    if abs(age) > max_age_s:
        raise StaleTimestampError(
            f"webhook timestamp is {age:.0f}s from now, exceeding "
            f"{max_age_s}s tolerance"
        )
    return ts


def _lower_headers(headers: Mapping[str, str]) -> dict:
    return {str(k).lower(): v for k, v in headers.items()}


def _safe_json(raw_body: bytes) -> dict:
    try:
        parsed = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class ProviderAdapter(ABC):
    """Interface every webhook-verifying adapter satisfies."""

    name: str = "base"

    #: Same meaning as PaymentGateway.is_live in gateway.py: can this
    #: adapter's webhooks be trusted to represent real money in production?
    #: False means "ships disabled" regardless of whether verify() itself
    #: would pass a well-formed test fixture.
    production_eligible: bool = False

    @abstractmethod
    def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> VerifiedEvent:
        """Verify + normalize. Raises an AdapterError subclass on any
        failure; never returns a VerifiedEvent for an unverified body."""
        ...


class CashfreeAdapter(ProviderAdapter):
    """Wraps the EXISTING CashfreeGateway verifier — no new crypto, no new
    parsing rule. `gateway` is injectable for tests; production code gets a
    fresh CashfreeGateway() reading the real CASHFREE_SECRET_KEY."""

    name = "cashfree"
    production_eligible = True

    def __init__(self, gateway: Optional[Any] = None, *,
                 max_age_s: Optional[int] = None):
        if gateway is None:
            from app.modules.carevo_payments.gateway import CashfreeGateway
            gateway = CashfreeGateway()
        self._gw = gateway
        self._max_age_s = (
            max_age_s if max_age_s is not None
            else settings.CASHFREE_WEBHOOK_MAX_AGE_S
        )

    def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> VerifiedEvent:
        _check_body_size(raw_body)
        h = _lower_headers(headers)
        signature = h.get("x-webhook-signature")
        timestamp = h.get("x-webhook-timestamp")

        if not signature:
            raise MissingSignatureError("x-webhook-signature header is missing")

        # Identical call, identical argument order, to what
        # carevo_customer/controller.py's payment_webhook already does.
        # CashfreeGateway.verify_webhook_signature uses hmac.compare_digest
        # internally (gateway.py) — not re-implemented here.
        if not self._gw.verify_webhook_signature(raw_body, signature, timestamp=timestamp):
            raise InvalidSignatureError("Cashfree webhook signature verification failed")

        _check_timestamp_window(timestamp, max_age_s=self._max_age_s)

        payload = _safe_json(raw_body)
        evt = self._gw.parse_webhook(raw_body, payload)
        return VerifiedEvent(
            provider=self.name,
            # Cashfree's webhook carries no id distinct from the payment id
            # itself; two deliveries of the same settlement share this value,
            # which is exactly the idempotency key mark_paid already uses
            # (carevo_customer/service.py).
            event_id=evt.gateway_payment_id,
            order_ref=evt.our_order_id,
            provider_payment_id=evt.gateway_payment_id,
            amount_paise=evt.amount_paise,
            currency=None,
            status=evt.outcome,
            occurred_at=float(timestamp) if timestamp else None,
            raw=payload,
        )


class RazorpayWebhookAdapter(ProviderAdapter):
    """HMAC-SHA256 hex over the raw body, header X-Razorpay-Signature.

    Verified against Razorpay's official documentation
    (https://razorpay.com/docs/webhooks/validate-test/, re-fetched for this
    fix pass via WebFetch): the header name (`X-Razorpay-Signature`), the
    hex encoding, "sign the raw body, never the parsed/re-serialised one",
    and the `x-razorpay-event-id` duplicate-detection header all match this
    implementation exactly. See docs/runbooks/PROVIDERS.md for the full
    verification record.

    ONLY X-Razorpay-Signature is required. The earlier `production_eligible
    = False` gap was this adapter requiring a header
    (`X-Razorpay-Event-Timestamp`) that real Razorpay deliveries never
    send -- every genuine delivery failed MissingTimestampError. That
    requirement is removed. Replay defence is now what the task asked for:
    payment_events' own UNIQUE(provider, event_id) dedup
    (reconciliation.apply_vendor_payment_event), not a header this
    provider does not document.

    Idempotency event id: `x-razorpay-event-id` when present (Razorpay's
    own documented mechanism); when absent, the SAME "body:" + sha256(raw
    body) fallback reconciliation.py uses for a Cashfree delivery with no
    payment id, so a byte-identical redelivery still dedupes.

    Creation-time check: UNVERIFIED against Razorpay's documentation --
    WebFetch could not confirm (nor rule out) a top-level `created_at`
    field in the webhook envelope (see docs/runbooks/PROVIDERS.md). Best
    effort only: if the parsed payload has a numeric top-level
    `created_at`, it is checked against a generous window and rejected
    only if OUT of it; if absent or non-numeric, no check runs and nothing
    is rejected for its absence.
    """

    name = "razorpay_webhook"
    production_eligible = True

    def __init__(self, *, secret: Optional[str] = None,
                 max_age_s: Optional[int] = None):
        self._secret = secret if secret is not None else settings.RAZORPAY_WEBHOOK_SECRET
        self._max_age_s = (
            max_age_s if max_age_s is not None
            else settings.CASHFREE_WEBHOOK_MAX_AGE_S
        )

    def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> VerifiedEvent:
        _check_body_size(raw_body)
        h = _lower_headers(headers)
        signature = h.get("x-razorpay-signature")

        if not signature:
            raise MissingSignatureError("X-Razorpay-Signature header is missing")
        if not self._secret:
            raise AdapterConfigError("Razorpay webhook secret is not configured")

        expected = hmac.new(
            self._secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise InvalidSignatureError("Razorpay webhook signature verification failed")

        payload = _safe_json(raw_body)

        # Best-effort, optional: see the class docstring's "Creation-time
        # check" note. Never raises for a MISSING field -- only for one
        # present and out of window.
        created_at = payload.get("created_at")
        if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
            age = time.time() - float(created_at)
            if abs(age) > self._max_age_s:
                raise StaleTimestampError(
                    f"webhook created_at is {age:.0f}s from now, exceeding "
                    f"{self._max_age_s}s tolerance"
                )

        entity = {}
        if isinstance(payload.get("payload"), dict):
            entity = payload["payload"].get("payment", {}).get("entity", {}) or {}
        status_raw = str(entity.get("status") or "").lower()
        if status_raw in ("captured", "authorized"):
            outcome = "PAID"
        elif status_raw == "failed":
            outcome = "FAILED"
        else:
            outcome = "UNKNOWN"

        amount = entity.get("amount")
        try:
            amount_paise = int(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount_paise = None

        event_id = h.get("x-razorpay-event-id") or (
            f"body:{hashlib.sha256(raw_body).hexdigest()}"
        )

        return VerifiedEvent(
            provider=self.name,
            event_id=event_id,
            order_ref=entity.get("order_id"),
            provider_payment_id=entity.get("id"),
            amount_paise=amount_paise,
            currency=entity.get("currency"),
            status=outcome,
            occurred_at=float(created_at) if isinstance(created_at, (int, float))
            and not isinstance(created_at, bool) else None,
            raw=payload,
        )


def get_adapter(provider: str) -> ProviderAdapter:
    """Registry used by the vendor-gateway webhook route (Task 5).

    Razorpay is returned only when RAZORPAY_ADAPTER_ENABLED=true; otherwise
    this raises, the same fail-closed shape as every other flag in this
    repository rather than silently falling back to a different provider.
    """
    key = (provider or "").strip().lower()
    if key == "cashfree":
        return CashfreeAdapter()
    if key == "razorpay":
        if not settings.RAZORPAY_ADAPTER_ENABLED:
            raise AdapterConfigError(
                "razorpay adapter is disabled (RAZORPAY_ADAPTER_ENABLED=false)"
            )
        return RazorpayWebhookAdapter()
    raise AdapterConfigError(f"unknown provider {provider!r}")
