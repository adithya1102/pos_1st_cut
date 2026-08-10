"""Auth + Security coverage."""
import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio


# ------------------------------- Auth ---------------------------------------
class TestAuth:
    async def test_staff_login_rejects_wrong_password(self, client, seed):
        r = await client.post(f"{API}/auth/login", data={
            "username": seed["owner_username"], "password": "definitely-wrong"})
        assert r.status_code == 401
        assert "Incorrect" in r.json()["detail"]

    async def test_customer_route_requires_token(self, client):
        r = await client.get(f"{API}/customer/me")
        assert r.status_code in (401, 403)

    async def test_customer_token_resolves_to_that_customer(self, client, seed):
        r = await client.get(f"{API}/customer/me", headers=seed["customer_auth"])
        assert r.status_code == 200
        assert r.json()["id"] == seed["customer_id"]

    async def test_garbage_token_rejected(self, client):
        r = await client.get(f"{API}/customer/me",
                             headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401


# ----------------------------- Security -------------------------------------
class TestSecurity:
    async def test_customer_token_cannot_reach_staff_routes(self, client, seed):
        """typ=customer must be refused by get_current_staff, not merely
        unauthorized-by-role."""
        r = await client.get(f"{API}/pos/orders", headers=seed["customer_auth"])
        assert r.status_code == 401

    async def test_staff_token_cannot_reach_customer_routes(self, client, seed):
        r = await client.get(f"{API}/customer/me", headers=seed["owner_auth"])
        assert r.status_code == 401

    async def test_non_admin_staff_blocked_from_admin(self, client, seed):
        r = await client.get(f"{API}/admin/promotions", headers=seed["owner_auth"])
        assert r.status_code == 403
        assert "SUPER_ADMIN" in r.json()["detail"]

    async def test_admin_allowed(self, client, seed):
        r = await client.get(f"{API}/admin/promotions", headers=seed["admin_auth"])
        assert r.status_code == 200

    async def test_owner_cannot_read_another_outlets_order(self, client, seed, db,
                                                           paid_order):
        """Ownership scoping: reject on someone else's order must 404, and must
        NOT reveal that the order exists."""
        import uuid as _u
        other_outlet, other_user = _u.uuid4(), _u.uuid4()
        org = await db.scalar(text("SELECT organization_id FROM outlets WHERE id=:o"),
                              {"o": seed["outlet_id"]})
        await db.execute(text(
            "INSERT INTO outlets (id, organization_id, location_name, is_visible, "
            "geofence_radius_meters, verification_status, created_at) "
            "VALUES (:i,:g,'Other', true, 150, 'active', now())"),
            {"i": str(other_outlet), "g": str(org)})
        await db.execute(text(
            "INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)"
            " VALUES (:i,:u,'x',true,:o, now())"),
            {"i": str(other_user), "u": f"other_{seed['tag']}", "o": str(other_outlet)})
        await db.commit()
        from app.core.auth import create_access_token
        token = create_access_token(subject="other_" + seed["tag"])
        hdr = {"Authorization": f"Bearer {token}"}
        r = await client.post(f"{API}/pos/orders/{paid_order['id']}/reject", headers=hdr)
        assert r.status_code == 404

    async def test_webhook_rejects_unsigned_when_secret_configured(self, client, monkeypatch):
        """With the stub and no webhook secret the endpoint accepts anything;
        that is only safe because the stub is not a real gateway. Assert the
        Cashfree gateway fails CLOSED instead."""
        from app.modules.carevo_payments.gateway import CashfreeGateway
        cf = CashfreeGateway()
        cf.secret_key = None
        assert cf.verify_webhook_signature(b"{}", "sig", timestamp="1") is False
        cf.secret_key = "s"
        assert cf.verify_webhook_signature(b"{}", None, timestamp="1") is False
        assert cf.verify_webhook_signature(b"{}", "sig", timestamp=None) is False
