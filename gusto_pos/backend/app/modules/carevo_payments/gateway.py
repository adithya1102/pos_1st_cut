"""
CareVo Skip — payment gateway abstraction.

Env-driven. No hardcoded keys. A `StubRazorpayGateway` produces razorpay-shaped
ids so the whole customer flow is walkable without real credentials, while the
same interface can later be backed by a real Razorpay client.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings


@dataclass
class GatewayOrder:
    gateway: str
    gateway_order_id: str
    amount: int          # minor units (paise)
    currency: str
    key_id: Optional[str]


class PaymentGateway(ABC):
    """Interface every gateway implementation must satisfy."""

    name: str = "base"

    @abstractmethod
    def create_order(self, amount_rupees: float, currency: str = "INR",
                     receipt: Optional[str] = None) -> GatewayOrder:
        ...

    @abstractmethod
    def verify_webhook_signature(self, body: bytes, signature: Optional[str]) -> bool:
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

    def create_order(self, amount_rupees: float, currency: str = "INR",
                     receipt: Optional[str] = None) -> GatewayOrder:
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

    def verify_webhook_signature(self, body: bytes, signature: Optional[str]) -> bool:
        # Stub mode: if no webhook secret configured, accept everything.
        if not self.webhook_secret:
            return True
        if not signature:
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def get_gateway() -> PaymentGateway:
    """Factory selected by PAYMENT_GATEWAY / PAYMENT_GATEWAY_SHAPE settings."""
    shape = (settings.PAYMENT_GATEWAY_SHAPE or "razorpay").lower()
    # Only a razorpay-shaped stub exists today; extend here for real gateways.
    if shape == "razorpay":
        return StubRazorpayGateway()
    return StubRazorpayGateway()
