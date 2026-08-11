"""Loyalty, promotions, push, account deletion, and admin."""
import pytest
from sqlalchemy import text

API = "/api/v1"

pytestmark = pytest.mark.asyncio


class TestLoyalty:
    async def test_points_accrue_on_payment(self, client, seed, paid_order, db):
        pts = await db.scalar(text("SELECT points_balance FROM customers WHERE id=:c"),
                              {"c": seed["customer_id"]})
        assert float(pts) == pytest.approx(200 * 0.005)   # 0.005 pts/rupee

    async def test_accrual_is_once_per_order(self, client, seed, paid_order, db):
        await client.post(f"{API}/customer/payment/simulate", headers=seed["customer_auth"],
                          json={"order_id": paid_order["id"], "method": "upi"})
        n = await db.scalar(text(
            "SELECT count(*) FROM point_transactions WHERE order_id=:o AND reason='ORDER_ACCRUAL'"),
            {"o": paid_order["id"]})
        assert n == 1, "idx_point_txn_one_accrual_per_order must hold"

    async def test_redeem_below_threshold_is_409(self, client, seed):
        r = await client.post(f"{API}/customer/points/redeem", headers=seed["customer_auth"])
        assert r.status_code == 409


class TestPromotions:
    async def test_owner_cannot_create_uncapped_percentage_offer(self, client, seed):
        r = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"],
                              json={"discount_type": "PERCENT", "discount_value": 20})
        assert r.status_code == 422
        assert "maximum discount" in str(r.json()).lower()

    async def test_owner_can_create_capped_percentage_offer(self, client, seed):
        r = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "PERCENT", "discount_value": 20,
            "max_discount_amount": 60, "is_active": True})
        assert r.status_code == 201, r.text
        assert r.json()["benefit_text"].startswith("20% off up to")

    async def test_patch_cannot_strip_the_cap(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 30, "is_active": True})
        pid = c.json()["id"]
        r = await client.patch(f"{API}/pos/offers/{pid}", headers=seed["owner_auth"],
                               json={"discount_type": "PERCENT"})
        assert r.status_code == 422, "merged-row guardrail must catch this"

    async def test_offer_scoped_to_own_outlet(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 25, "is_active": True})
        assert c.json()["scope"] == "RESTAURANT_OFFER"
        assert c.json()["outlet_id"] == seed["outlet_id"]

    async def test_admin_campaign_is_carevo_scoped(self, client, seed):
        r = await client.post(f"{API}/admin/promotions", headers=seed["admin_auth"], json={
            "label": "Welcome", "discount_type": "FLAT", "discount_value": 50,
            "is_active": True})
        assert r.status_code == 201, r.text
        assert r.json()["scope"] == "CAREVO_CAMPAIGN"

    async def test_customer_sees_campaign_and_offer_merged(self, client, seed):
        await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 25, "is_active": True})
        await client.post(f"{API}/admin/promotions", headers=seed["admin_auth"], json={
            "label": "Platform", "discount_type": "FLAT", "discount_value": 50,
            "is_active": True})
        r = await client.get(f"{API}/customer/offers?outlet_id={seed['outlet_id']}",
                             headers=seed["customer_auth"])
        scopes = {o["scope"] for o in r.json()}
        assert scopes == {"RESTAURANT_OFFER", "CAREVO_CAMPAIGN"}

    async def test_inactive_offer_hidden_from_customer(self, client, seed):
        await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 25, "is_active": False})
        r = await client.get(f"{API}/customer/offers?outlet_id={seed['outlet_id']}",
                             headers=seed["customer_auth"])
        # Platform-wide CareVo campaigns created by other tests legitimately
        # reach every outlet, so scope the assertion to this outlet's own offers.
        own = [o for o in r.json() if o["scope"] == "RESTAURANT_OFFER"]
        assert own == []

    async def test_promotion_applies_and_is_recorded(self, client, seed, db):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "PERCENT", "discount_value": 20,
            "max_discount_amount": 60, "is_active": True})
        pid = c.json()["id"]
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
            "promotion_id": pid})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["original_amount"] == 200.0
        assert b["discount_amount"] == 40.0        # 20% of 200, under the 60 cap
        assert b["final_amount"] == 160.0
        n = await db.scalar(text(
            "SELECT count(*) FROM promotion_redemptions WHERE promotion_id=:p"), {"p": pid})
        assert n == 1

    async def test_percentage_cap_binds(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "PERCENT", "discount_value": 50,
            "max_discount_amount": 10, "is_active": True})
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 2}],
            "promotion_id": c.json()["id"]})
        assert r.json()["discount_amount"] == 10.0

    async def test_per_customer_cap_blocks_second_use(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 20, "is_active": True})
        pid = c.json()["id"]
        body = {"outlet_id": seed["outlet_id"],
                "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
                "promotion_id": pid}
        first = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json=body)
        assert first.status_code == 200
        second = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json=body)
        assert second.status_code == 422
        assert "already used" in second.json()["detail"].lower()

    async def test_min_order_value_enforced(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 20,
            "min_order_value": 5000, "is_active": True})
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "promotion_id": c.json()["id"]})
        assert r.status_code == 422
        assert "more" in r.json()["detail"]

    async def test_no_stacking_coupon_and_promotion(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 20, "is_active": True})
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "promotion_id": c.json()["id"], "coupon_code": "PTS-FAKE1234"})
        assert r.status_code == 422
        assert "not both" in r.json()["detail"]


class TestPush:
    async def test_staff_can_register_token(self, client, seed, db):
        r = await client.post(f"{API}/pos/push/register", headers=seed["owner_auth"],
                              json={"fcm_token": "test-token-abcdefghij"})
        assert r.status_code == 200
        tok = await db.scalar(text("SELECT fcm_token FROM users WHERE id=:u"),
                              {"u": seed["owner_id"]})
        assert tok == "test-token-abcdefghij"

    async def test_new_paid_order_logs_staff_push(self, client, seed, db):
        await client.post(f"{API}/pos/push/register", headers=seed["owner_auth"],
                          json={"fcm_token": "test-token-abcdefghij"})
        from app.modules.push.service import PushService
        from app.modules.carevo_customer.model import CustomerOrder
        from sqlalchemy import select
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}]})
        oid = r.json()["id"]
        await client.post(f"{API}/customer/payment/simulate", headers=seed["customer_auth"],
                          json={"order_id": oid, "method": "upi"})
        order = (await db.execute(select(CustomerOrder).where(
            CustomerOrder.id == oid))).scalars().first()
        await PushService.notify_outlet_new_order(db, order)
        await db.commit()
        row = (await db.execute(text(
            "SELECT kind,status FROM push_notifications WHERE order_id=:o AND kind='STAFF_NEW_ORDER'"),
            {"o": oid})).first()
        # 'skipped' is correct here: push is not configured in the test env.
        # What this proves is that migration 018 lets the row exist at all.
        assert row is not None and row[1] in ("sent", "skipped")


class TestAccountDeletion:
    async def test_delete_anonymises_and_keeps_orders(self, client, seed, paid_order, db):
        r = await client.delete(f"{API}/customer/me", headers=seed["customer_auth"])
        assert r.status_code == 200, r.text
        assert r.json()["orders_retained"] >= 1

        row = (await db.execute(text(
            "SELECT name,email,phone_number,google_uid,points_balance "
            "FROM customers WHERE id=:c"), {"c": seed["customer_id"]})).first()
        assert row[0] is None and row[1] is None and row[2] is None
        assert row[3].startswith("deleted:")
        assert float(row[4]) == 0

        # order history survives, and the append-only event log is untouched
        n = await db.scalar(text("SELECT count(*) FROM customer_orders WHERE customer_id=:c"),
                            {"c": seed["customer_id"]})
        assert n >= 1
        orphans = await db.scalar(text(
            "SELECT count(*) FROM order_events e LEFT JOIN customer_orders o "
            "ON o.id=e.order_id WHERE o.id IS NULL"))
        assert orphans == 0

    async def test_deleted_account_token_no_longer_resolves_identity(self, client, seed):
        await client.delete(f"{API}/customer/me", headers=seed["customer_auth"])
        r = await client.get(f"{API}/customer/me", headers=seed["customer_auth"])
        # the row survives (it holds order history), but carries no identity
        if r.status_code == 200:
            assert r.json()["phone_number"] is None and r.json()["email"] is None


class TestAdmin:
    async def test_admin_lists_only_campaigns(self, client, seed):
        await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 25, "is_active": True})
        await client.post(f"{API}/admin/promotions", headers=seed["admin_auth"], json={
            "label": "C", "discount_type": "FLAT", "discount_value": 50})
        r = await client.get(f"{API}/admin/promotions", headers=seed["admin_auth"])
        assert all(p["scope"] == "CAREVO_CAMPAIGN" for p in r.json())

    async def test_campaign_toggle_is_audited(self, client, seed, db):
        c = await client.post(f"{API}/admin/promotions", headers=seed["admin_auth"], json={
            "label": "Audit me", "discount_type": "FLAT", "discount_value": 50})
        pid = c.json()["id"]
        await client.patch(f"{API}/admin/promotions/{pid}", headers=seed["admin_auth"],
                           json={"is_active": True})
        actions = [r[0] for r in (await db.execute(text(
            "SELECT action FROM admin_audit_logs WHERE target_id=:t ORDER BY created_at"),
            {"t": pid})).fetchall()]
        assert "promotion.create" in actions
        assert "promotion.activate" in actions

    async def test_deleted_customers_hidden_from_directory(self, client, seed, paid_order):
        await client.delete(f"{API}/customer/me", headers=seed["customer_auth"])
        r = await client.get(f"{API}/admin/customers", headers=seed["admin_auth"])
        assert seed["customer_id"] not in [c["id"] for c in r.json()]

    async def test_redemption_count_reported(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 20, "is_active": True})
        pid = c.json()["id"]
        await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "promotion_id": pid})
        r = await client.get(f"{API}/pos/offers", headers=seed["owner_auth"])
        mine = [p for p in r.json() if p["id"] == pid][0]
        assert mine["redemption_count"] == 1


class TestAdminOrders:
    async def test_orders_gated_and_paginated(self, client, seed, paid_order):
        assert (await client.get(f"{API}/admin/orders",
                                 headers=seed["owner_auth"])).status_code == 403
        r = await client.get(f"{API}/admin/orders?limit=5&offset=0",
                             headers=seed["admin_auth"])
        assert r.status_code == 200
        page = r.json()
        assert {"total", "limit", "offset", "orders"} <= set(page)
        assert page["limit"] == 5 and page["offset"] == 0
        assert page["total"] >= 1

    async def test_order_row_carries_the_reporting_fields(self, client, seed, paid_order):
        r = await client.get(f"{API}/admin/orders?limit=50", headers=seed["admin_auth"])
        row = next(o for o in r.json()["orders"] if o["order_id"] == paid_order["id"])
        assert row["pickup_code"]
        assert row["outlet_name"]
        assert row["customer_name"]
        assert row["total_amount"] == 200.0
        assert [i["name"] for i in row["items"]] == ["Test Dish"]

    async def test_distance_is_null_when_origin_never_captured(self, client, seed,
                                                               paid_order):
        r = await client.get(f"{API}/admin/orders?limit=50", headers=seed["admin_auth"])
        row = next(o for o in r.json()["orders"] if o["order_id"] == paid_order["id"])
        # Never fabricate a distance — no origin means unknown, not zero.
        assert row["distance_km"] is None

    async def test_distance_computed_when_origin_present(self, client, seed, db):
        await db.execute(text(
            "UPDATE outlets SET latitude=12.9716, longitude=77.5946 WHERE id=:o"),
            {"o": seed["outlet_id"]})
        await db.commit()
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "origin_lat": 13.0827, "origin_lng": 80.2707, "origin_source": "gps"})
        oid = r.json()["id"]
        page = await client.get(f"{API}/admin/orders?limit=50", headers=seed["admin_auth"])
        row = next(o for o in page.json()["orders"] if o["order_id"] == oid)
        # Bengaluru -> Chennai is ~290km; assert the order of magnitude only.
        assert row["distance_km"] is not None and 250 < row["distance_km"] < 350

    async def test_promotion_surfaces_on_the_order_row(self, client, seed):
        c = await client.post(f"{API}/pos/offers", headers=seed["owner_auth"], json={
            "discount_type": "FLAT", "discount_value": 20, "is_active": True})
        r = await client.post(f"{API}/customer/orders", headers=seed["customer_auth"], json={
            "outlet_id": seed["outlet_id"],
            "items": [{"menu_item_id": seed["menu_item_id"], "quantity": 1}],
            "promotion_id": c.json()["id"]})
        oid = r.json()["id"]
        page = await client.get(f"{API}/admin/orders?limit=50", headers=seed["admin_auth"])
        row = next(o for o in page.json()["orders"] if o["order_id"] == oid)
        assert row["promotion_label"] and row["promotion_discount"] == 20.0

    async def test_history_now_carries_pickup_code(self, client, seed, paid_order):
        r = await client.get(f"{API}/customer/orders", headers=seed["customer_auth"])
        row = next(o for o in r.json() if o["order_id"] == paid_order["id"])
        # The persistence fix: history alone is enough to recover the code.
        assert row["pickup_code"], "history must expose the code, not just checkout"
