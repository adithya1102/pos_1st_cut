"""
CareVo Skip end-to-end smoke test.

Seeds a minimal, self-contained dataset (org/outlet/menu/category/item/staff-user
— DATA inserts only, no DDL) then drives the full flow against a locally-running
server:

  request-otp -> verify-otp -> create order -> simulate payment
  -> get order (pickup_code present) -> staff verify-pickup (correct)
  -> wrong code x3 -> lockout

Run the server first:
  PYTHONPATH=$(pwd) python -m uvicorn app.main:app --port 8000

Then:
  PYTHONPATH=$(pwd) python scripts/smoke_carevo.py
"""
import asyncio
import sys
import uuid

import httpx
from sqlalchemy import text

from app.core.database import engine
from app.core.auth import create_access_token
from app.core.security import get_password_hash

BASE = "http://127.0.0.1:8000/api/v1"

# Fixed ids so the script is idempotent / re-runnable.
ORG_ID = "11111111-1111-1111-1111-111111111111"
OUTLET_ID = "22222222-2222-2222-2222-222222222222"
MENU_ID = "33333333-3333-3333-3333-333333333333"
CAT_ID = "44444444-4444-4444-4444-444444444444"
ITEM_ID = "55555555-5555-5555-5555-555555555555"
USER_ID = "66666666-6666-6666-6666-666666666666"
PHONE = "9998887770"


async def seed():
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO organizations (id, name, created_at) VALUES (:id,'Smoke Org', now()) ON CONFLICT (id) DO NOTHING"), {"id": ORG_ID})
        await c.execute(text("""
            INSERT INTO outlets (id, location_name, city, latitude, longitude, geofence_radius_meters, organization_id, created_at)
            VALUES (:id,'Smoke Outlet','Bengaluru', 12.9716, 77.5946, 100, :org, now())
            ON CONFLICT (id) DO NOTHING
        """), {"id": OUTLET_ID, "org": ORG_ID})
        await c.execute(text("INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) VALUES (:id,:o,'v1',true, now()) ON CONFLICT (id) DO NOTHING"), {"id": MENU_ID, "o": OUTLET_ID})
        await c.execute(text("INSERT INTO categories (id, menu_id, name, created_at) VALUES (:id,:m,'Mains', now()) ON CONFLICT (id) DO NOTHING"), {"id": CAT_ID, "m": MENU_ID})
        await c.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg, is_active, is_available, prep_time_minutes, tags, created_at)
            VALUES (:id,:c,'Paneer Tikka', 250.00, true, true, true, 12, '["chef-special"]'::json, now())
            ON CONFLICT (id) DO NOTHING
        """), {"id": ITEM_ID, "c": CAT_ID})
        await c.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)
            VALUES (:id,'smoke_staff', :pw, true, :o, now())
            ON CONFLICT (id) DO NOTHING
        """), {"id": USER_ID, "pw": get_password_hash("staffpin"), "o": OUTLET_ID})
    print("[seed] done")


async def cleanup():
    async with engine.begin() as c:
        # Remove customer orders created by this smoke customer, then seed rows.
        await c.execute(text("""
            DELETE FROM customer_orders WHERE customer_id IN
              (SELECT id FROM customers WHERE phone_number = :p)
        """), {"p": PHONE})
        await c.execute(text("DELETE FROM customers WHERE phone_number = :p"), {"p": PHONE})
        await c.execute(text("DELETE FROM menu_items WHERE id=:i"), {"i": ITEM_ID})
        await c.execute(text("DELETE FROM categories WHERE id=:i"), {"i": CAT_ID})
        await c.execute(text("DELETE FROM menus WHERE id=:i"), {"i": MENU_ID})
        await c.execute(text("DELETE FROM users WHERE id=:i"), {"i": USER_ID})
        await c.execute(text("DELETE FROM outlets WHERE id=:i"), {"i": OUTLET_ID})
        await c.execute(text("DELETE FROM organizations WHERE id=:i"), {"i": ORG_ID})
    print("[cleanup] done")


def ok(cond, msg):
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        raise SystemExit(f"ASSERTION FAILED: {msg}")


async def run_flow():
    async with httpx.AsyncClient(timeout=30) as x:
        # 1. request-otp
        r = await x.post(f"{BASE}/customer/auth/request-otp", json={"phone_number": PHONE})
        print("request-otp:", r.status_code, r.json())
        ok(r.status_code == 200 and r.json().get("stub") is True, "request-otp returns stub request_id")

        # 2. verify-otp
        r = await x.post(f"{BASE}/customer/auth/verify-otp", json={"phone_number": PHONE, "otp": "000000"})
        print("verify-otp:", r.status_code, r.json())
        ok(r.status_code == 200, "verify-otp 200")
        token = r.json()["access_token"]
        cust = {"Authorization": f"Bearer {token}"}

        # 2b. outlets discovery
        r = await x.get(f"{BASE}/customer/outlets", params={"lat": 12.97, "lng": 77.59}, headers=cust)
        print("outlets:", r.status_code, "count", len(r.json()))
        ok(r.status_code == 200 and any(str(o["id"]) == OUTLET_ID for o in r.json()), "smoke outlet listed with distance")

        # 2c. menu
        r = await x.get(f"{BASE}/customer/menu/{OUTLET_ID}", headers=cust)
        print("menu:", r.status_code)
        ok(r.status_code == 200 and r.json()["categories"], "menu returns categories+items")

        # 3. create order
        r = await x.post(f"{BASE}/customer/orders", headers=cust, json={
            "outlet_id": OUTLET_ID,
            "items": [{"menu_item_id": ITEM_ID, "quantity": 2}],
            "customer_notes": "no onion",
        })
        print("create order:", r.status_code, r.json())
        ok(r.status_code == 200, "create order 200")
        body = r.json()
        order_id = body["id"]
        ok(body["total_amount"] == 500.0, "total_amount computed server-side (2x250)")
        ok(body["payment"]["gateway_order_id"].startswith("order_"), "razorpay-shaped gateway_order_id")

        # 4. simulate payment
        r = await x.post(f"{BASE}/customer/payment/simulate", headers=cust, json={"order_id": order_id, "method": "upi"})
        print("simulate:", r.status_code, r.json())
        ok(r.status_code == 200 and r.json()["status"] == "PAID", "simulate -> PAID")
        pickup_code = r.json()["pickup_code"]
        ok(bool(pickup_code) and len(pickup_code) == 6, "pickup_code generated (6 chars)")

        # 4b. simulate again -> idempotent (same pickup_code, still PAID)
        r = await x.post(f"{BASE}/customer/payment/simulate", headers=cust, json={"order_id": order_id, "method": "upi"})
        ok(r.status_code == 200 and r.json()["pickup_code"] == pickup_code, "simulate idempotent (same pickup_code)")

        # 5. get order
        r = await x.get(f"{BASE}/customer/orders/{order_id}", headers=cust)
        print("get order:", r.status_code, {k: r.json()[k] for k in ("status", "payment_status", "pickup_code")})
        ok(r.status_code == 200 and r.json()["pickup_code"] == pickup_code, "get order shows pickup_code")

        # staff token (mint like pin-login does: subject = user id)
        staff_tok = create_access_token(subject=USER_ID)
        staff = {"Authorization": f"Bearer {staff_tok}"}

        # --- HAPPY PATH: a second order, correct code -> COMPLETED ---
        r = await x.post(f"{BASE}/customer/orders", headers=cust, json={
            "outlet_id": OUTLET_ID, "items": [{"menu_item_id": ITEM_ID, "quantity": 1}]})
        order2 = r.json()["id"]
        r = await x.post(f"{BASE}/customer/payment/simulate", headers=cust, json={"order_id": order2, "method": "upi"})
        code2 = r.json()["pickup_code"]
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff, json={"order_id": order2, "pickup_code": code2})
        print("verify correct:", r.status_code, r.json())
        ok(r.status_code == 200 and r.json().get("verified") is True and r.json().get("status") == "COMPLETED",
           "staff verify-pickup (correct) -> COMPLETED")

        # 5b. customer token must be REJECTED on staff route
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=cust, json={"order_id": order_id, "pickup_code": pickup_code})
        print("verify with customer token:", r.status_code)
        ok(r.status_code == 401, "customer token rejected on staff verify-pickup")

        # 6. staff verify-pickup with WRONG code x3 -> lockout
        for i in range(1, 4):
            r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff, json={"order_id": order_id, "pickup_code": "000000" if pickup_code != "000000" else "ZZZZZZ"})
            print(f"wrong attempt {i}:", r.status_code, r.json())
            j = r.json()
            ok(j.get("verified") is False, f"wrong attempt {i} not verified")
            if i < 3:
                ok(j.get("attempts_remaining") == 3 - i, f"attempts_remaining={3-i}")
            else:
                ok(j.get("locked") is True, "locked after 3rd wrong attempt")

        # 7. now even correct code is blocked (locked) -> 423
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff, json={"order_id": order_id, "pickup_code": pickup_code})
        print("correct after lock:", r.status_code, r.text[:120])
        ok(r.status_code == 423, "locked order returns 423 even with correct code")

        print("\nALL SMOKE CHECKS PASSED")


async def main():
    await cleanup()   # start clean
    await seed()
    try:
        await run_flow()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
