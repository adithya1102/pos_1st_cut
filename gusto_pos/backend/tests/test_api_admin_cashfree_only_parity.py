"""Task 4 — admin payment-methods switch parity with the owner route.

LITERAL BEHAVIOUR BEFORE THIS FILE: AdminService.set_payment_methods
(carevo_admin/service.py) had no CASHFREE_ONLY check at all. While
CASHFREE_ONLY=true refused the OWNER route's attempt to turn pay-at-pickup or
UPI on (403 CASHFREE_ONLY_MODE — carevo_customer/service.py
set_owner_payment_methods), a SUPER_ADMIN hitting
PATCH /api/v1/admin/outlets/{id}/payment-methods could silently re-enable
either for one outlet, defeating the platform-wide switch through the one
route that was supposed to be MORE restrictive, not less.

The fix mirrors the owner route's guard exactly, checked first before any
other rule, in AdminService.set_payment_methods.
"""
from __future__ import annotations

from app.core.config import settings
from tests.conftest import API


def _admin_patch_url(outlet_id):
    return f"{API}/admin/outlets/{outlet_id}/payment-methods"


class TestAdminSwitchParity:
    async def test_refused_turning_pickup_on_with_switch_on(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": True})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["error"] == "CASHFREE_ONLY_MODE"

    async def test_refused_turning_upi_on_with_switch_on(
            self, client, seed, monkeypatch):
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "upi_manual": True})
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["error"] == "CASHFREE_ONLY_MODE"

    async def test_unchanged_turning_pickup_on_with_switch_off(
            self, client, seed, monkeypatch):
        """The control: with CASHFREE_ONLY off (default), the SAME request
        that the switch-on test refuses must still work exactly as it did
        before this file — the guard must not have become unconditional."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", False)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": True})
        assert r.status_code == 200, r.text
        assert r.json()["payment_pay_at_pickup_enabled"] is True

    async def test_unchanged_turning_upi_on_with_switch_off(
            self, client, db, seed, monkeypatch):
        from sqlalchemy import text
        # ck_outlets_upi_manual_requires_vpa needs a VPA on file before the
        # flag can go true, regardless of CASHFREE_ONLY — seed it directly,
        # same as the owner-route equivalent test does.
        await db.execute(text(
            "UPDATE outlets SET upi_vpa = 'owner@okaxis', "
            "upi_payee_name = 'Owner', upi_attested_at = now() "
            "WHERE id = :o"), {"o": seed["outlet_id"]})
        await db.commit()

        monkeypatch.setattr(settings, "CASHFREE_ONLY", False)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": False, "pay_at_pickup": False,
                  "upi_manual": True})
        assert r.status_code == 200, r.text
        assert r.json()["payment_upi_manual_enabled"] is True

    async def test_prepaid_only_patch_still_succeeds_with_switch_on(
            self, client, seed, monkeypatch):
        """CASHFREE_ONLY refuses turning pickup/UPI ON. It must not refuse a
        request that leaves them off — the normal prepaid-only shape."""
        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "upi_manual": False, "cashfree_unlocked": True})
        assert r.status_code == 200, r.text

    async def test_turning_pickup_off_is_not_blocked_with_switch_on(
            self, client, db, seed, monkeypatch):
        """Switching pickup OFF while CASHFREE_ONLY is on must still work —
        the 403 is about turning it ON, not about touching the route."""
        from sqlalchemy import text
        await db.execute(text(
            "UPDATE outlets SET payment_pay_at_pickup_enabled = true, "
            "payment_prepaid_enabled = true WHERE id = :o"),
            {"o": seed["outlet_id"]})
        await db.commit()

        monkeypatch.setattr(settings, "CASHFREE_ONLY", True)
        r = await client.patch(
            _admin_patch_url(seed["outlet_id"]),
            headers=seed["admin_auth"],
            json={"prepaid": True, "pay_at_pickup": False,
                  "cashfree_unlocked": True})
        assert r.status_code == 200, r.text
        assert r.json()["payment_pay_at_pickup_enabled"] is False
