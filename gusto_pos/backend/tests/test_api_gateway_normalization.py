"""Task 2 (independent-verification fix) — one normalization for
PAYMENT_GATEWAY, shared by validate_gateway_startup_posture, get_gateway()
and _gateway_can_charge().

LITERAL BEHAVIOUR BEFORE THIS FILE: validate_gateway_startup_posture and
validate_cashfree_only_config (app/core/config.py) did `.strip().lower()`;
get_gateway() (carevo_payments/gateway.py) and _gateway_can_charge()
(carevo_customer/service.py) did `.lower()` only, with NO strip. For
PAYMENT_GATEWAY=" cashfree" (one leading space): the startup guard believed
Cashfree was configured and started in production with no
ALLOW_STUB_GATEWAY — while get_gateway() resolved it to the STUB and
_gateway_can_charge() returned False for it (neither "cashfree" nor "stub"
matched the un-stripped, lowercased string). Independently verified live:
the guard passes, checkout then returns 409 NO_EFFECTIVE_PAYMENT_METHOD /
PAYMENT_METHOD_UNAVAILABLE — a total, undetected outage of the only payment
method, caused by exactly the class of misconfiguration the guard exists to
catch.

FIXED: one function, normalize_payment_gateway (app/core/config.py), used by
all three call sites.
"""
from __future__ import annotations

from app.core.config import (
    PaymentConfigError,
    normalize_payment_gateway,
    settings,
    validate_gateway_startup_posture,
)
from app.modules.carevo_customer.service import _gateway_can_charge
from app.modules.carevo_payments.gateway import CashfreeGateway, get_gateway


CASHFREE_VARIANTS = [" cashfree", "Cashfree", "cashfree ", "CASHFREE", "cashfree"]
NON_CASHFREE_VALUES = ["unset", "stub", "", None, "razorpay"]


class TestNormalizeHelper:
    def test_strips_and_lowercases(self):
        for variant in CASHFREE_VARIANTS:
            assert normalize_payment_gateway(variant) == "cashfree", variant

    def test_none_and_empty_normalize_to_empty_string(self):
        assert normalize_payment_gateway(None) == ""
        assert normalize_payment_gateway("") == ""
        assert normalize_payment_gateway("   ") == ""


class TestThreePathsAgree:
    """The exact assertion the task asks for: for each of unset, stub,
    ' cashfree', 'CASHFREE', 'cashfree', all three paths reach the SAME
    conclusion about whether Cashfree is selected."""

    async def test_all_three_paths_agree_for_each_value(self, monkeypatch):
        cases = ["unset", "stub", " cashfree", "CASHFREE", "cashfree"]
        for value in cases:
            monkeypatch.setattr(settings, "PAYMENT_GATEWAY", value)

            guard_sees_cashfree = True
            try:
                validate_gateway_startup_posture(env_name="production", allow_stub="")
            except PaymentConfigError:
                guard_sees_cashfree = False

            gateway_is_cashfree = isinstance(get_gateway(), CashfreeGateway)
            can_charge = _gateway_can_charge()

            is_cashfree_value = normalize_payment_gateway(value) == "cashfree"
            assert guard_sees_cashfree == is_cashfree_value, value
            assert gateway_is_cashfree == is_cashfree_value, value
            # can_charge is True for BOTH cashfree and stub, so it only
            # has to agree with the guard/gateway when the value IS
            # cashfree; "stub" legitimately can_charge=True while not
            # being cashfree.
            if is_cashfree_value:
                assert can_charge is True, value


class TestLeadingSpaceNoLongerDivergesFromRuntime:
    async def test_leading_space_now_starts_and_actually_runs_cashfree(
            self, client, seed, monkeypatch):
        """The exact live reproduction from the independent verification,
        now closed: PAYMENT_GATEWAY=' cashfree' must no longer pass the
        startup guard while silently running the stub."""
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", " cashfree")

        validate_gateway_startup_posture(env_name="production", allow_stub="")

        resolved = get_gateway()
        assert isinstance(resolved, CashfreeGateway)
        assert resolved.is_live is True
        assert _gateway_can_charge() is True
