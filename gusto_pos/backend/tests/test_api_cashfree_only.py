"""CASHFREE_ONLY (config.py) — the one reversible switch that makes Cashfree
prepaid the only payment path on the whole platform.

Default is false, and OFF must be byte-for-byte identical to every test in
test_api_pay_at_pickup.py and test_api_manual_upi.py — those files are not
touched here. This file only adds coverage for the switch itself.

THE ASSERTION THAT MATTERS MOST
--------------------------------
`TestSwitchOff` — with CASHFREE_ONLY left at its default, payment_methods_for
offers pay-at-pickup and UPI exactly as before. If this regresses, the switch
has started changing behaviour nobody turned on.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.modules.carevo_customer.service import (
    PAY_AT_PICKUP, PAY_PREPAID, PAY_UPI_MANUAL, CarevoService,
)
from tests.conftest import API

SETTINGS = f"{API}/pos/outlet/payment-methods"


async def _set_methods(db, outlet_id, *, prepaid=True, pickup=False, upi=False,
                       cashfree_unlocked=True) -> None:
    await db.execute(text("""
        UPDATE outlets SET payment_prepaid_enabled = :p,
                           payment_pay_at_pickup_enabled = :k,
                           payment_upi_manual_enabled = :u,
                           cashfree_unlocked = :c,
                           is_manually_closed = false,
                           upi_vpa = CASE WHEN :u THEN 'test@okaxis'
                                          ELSE upi_vpa END,
                           upi_payee_name = CASE WHEN :u THEN 'Test Kitchen'
                                                 ELSE upi_payee_name END,
                           upi_attested_at = CASE WHEN :u THEN now()
                                                  ELSE upi_attested_at END
         WHERE id = :oid
    """), {"p": prepaid, "k": pickup, "u": upi, "c": cashfree_unlocked,
           "oid": str(outlet_id)})
    await db.commit()


async def _place(client, seed, *, method=None, outlet_id=None):
    body = {
        "outlet_id": outlet_id or seed["outlet_id"],
        "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
    }
    if method is not None:
        body["payment_method"] = method
    return await client.post(f"{API}/customer/orders",
                             headers=seed["customer_auth"], json=body)


# ============================ 1. switch OFF (default) ========================

class TestSwitchOff:
    """CASHFREE_ONLY defaults to False. Every branch here must behave exactly
    as the pre-existing pay-at-pickup/UPI test suites already prove — this
    class only re-states the headline cases so a regression here is loud."""

    def test_default_is_false(self):
        assert settings.CASHFREE_ONLY is False

    async def test_pickup_and_upi_still_offered(self, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True,
                           upi=True)
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_PREPAID, PAY_AT_PICKUP, PAY_UPI_MANUAL]

    async def test_create_order_accepts_pickup(self, client, db, seed):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        r = await _place(client, seed, method=PAY_AT_PICKUP)
        assert r.status_code == 200, r.text

    async def test_owner_can_turn_pickup_on(self, client, seed):
        r = await client.patch(SETTINGS, headers=seed["owner_auth"], json={
            "prepaid": True, "pay_at_pickup": True, "upi_manual": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["pay_at_pickup"] is True


# ============================ 2. switch ON: resolver ==========================

class TestSwitchOnResolver:
    """With CASHFREE_ONLY true, payment_methods_for never returns anything but
    PREPAID — or nothing — no matter what the outlet's own flags say."""

    async def test_prepaid_unlocked_outlet_gets_prepaid_only(
            self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True,
                           upi=True, cashfree_unlocked=True)
        methods = await CarevoService.payment_methods_for(db, seed["outlet_id"])
        assert methods == [PAY_PREPAID]

    async def test_not_unlocked_gets_nothing(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True,
                           upi=True, cashfree_unlocked=False)
        assert await CarevoService.payment_methods_for(db, seed["outlet_id"]) == []

    async def test_prepaid_flag_off_gets_nothing(self, db, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        await _set_methods(db, seed["outlet_id"], prepaid=False, pickup=True,
                           upi=True, cashfree_unlocked=True)
        assert await CarevoService.payment_methods_for(db, seed["outlet_id"]) == []

    async def test_no_gateway_selected_gets_nothing(
            self, db, seed, monkeypatch):
        """Even unlocked and flagged on, CASHFREE_ONLY still needs a working
        gateway — it does not conjure a payment provider either."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        monkeypatch.setattr(settings, "PAYMENT_GATEWAY", "unset")
        await _set_methods(db, seed["outlet_id"], prepaid=True,
                           cashfree_unlocked=True)
        assert await CarevoService.payment_methods_for(db, seed["outlet_id"]) == []


# ============================ 3. switch ON: create_order ======================

class TestSwitchOnCreateOrder:
    async def test_pay_at_pickup_rejected_with_409(
            self, client, db, seed, monkeypatch):
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True,
                           cashfree_unlocked=True)
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await _place(client, seed, method=PAY_AT_PICKUP)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_upi_manual_rejected_with_409(
            self, client, db, seed, monkeypatch):
        await _set_methods(db, seed["outlet_id"], prepaid=True, upi=True,
                           cashfree_unlocked=True)
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await _place(client, seed, method=PAY_UPI_MANUAL)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["error"] == "PAYMENT_METHOD_UNAVAILABLE"

    async def test_locked_outlet_refuses_default_prepaid_too(
            self, client, db, seed, monkeypatch):
        """An outlet not yet unlocked for Cashfree is left able to take no
        orders at all under CASHFREE_ONLY — the honest empty-list outcome."""
        await _set_methods(db, seed["outlet_id"], prepaid=True,
                           cashfree_unlocked=False)
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await _place(client, seed)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["available"] == []

    async def test_unlocked_prepaid_order_still_succeeds(
            self, client, db, seed, monkeypatch):
        await _set_methods(db, seed["outlet_id"], prepaid=True,
                           cashfree_unlocked=True)
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await _place(client, seed, method=PAY_PREPAID)
        assert r.status_code == 200, r.text


# ============================ 4. switch ON: owner settings ===================

class TestSwitchOnOwnerSettings:
    async def test_get_reports_cashfree_only_true(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_only"] is True

    async def test_get_reports_cashfree_only_false_by_default(
            self, client, seed):
        r = await client.get(SETTINGS, headers=seed["owner_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_only"] is False

    async def test_turning_pickup_on_is_403(self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(SETTINGS, headers=seed["owner_auth"], json={
            "prepaid": True, "pay_at_pickup": True, "upi_manual": False,
        })
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["error"] == "CASHFREE_ONLY_MODE"

    async def test_turning_upi_on_is_403(self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(SETTINGS, headers=seed["owner_auth"], json={
            "prepaid": True, "pay_at_pickup": False, "upi_manual": True,
            "upi_vpa": "owner@okaxis", "upi_payee_name": "Owner",
            "upi_attested": True,
        })
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["error"] == "CASHFREE_ONLY_MODE"

    async def test_prepaid_only_patch_still_succeeds(
            self, client, seed, monkeypatch):
        """CASHFREE_ONLY refuses turning pickup/UPI ON. It must not refuse a
        request that leaves them off — that is the normal prepaid-only shape
        every outlet is expected to converge on."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(SETTINGS, headers=seed["owner_auth"], json={
            "prepaid": True, "pay_at_pickup": False, "upi_manual": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["cashfree_only"] is True

    async def test_turning_pickup_off_is_not_blocked(
            self, client, db, seed, monkeypatch):
        """Switching OFF pickup/UPI while CASHFREE_ONLY is on must still work
        — the 403 is about turning them ON, not about touching the route."""
        await _set_methods(db, seed["outlet_id"], prepaid=True, pickup=True)
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(SETTINGS, headers=seed["owner_auth"], json={
            "prepaid": True, "pay_at_pickup": False, "upi_manual": False,
        })
        assert r.status_code == 200, r.text
        assert r.json()["pay_at_pickup"] is False
