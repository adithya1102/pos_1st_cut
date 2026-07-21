"""
CareVo Skip — functional test suite (Part 2 of the regression/QA task).

Runs against a LIVE server (the in-memory OTP rate-limiter lives in the server
process, so rate-limit assertions MUST hit HTTP). Seeds a self-contained,
clearly-marked (TEST_CAREVO_) fixture set via DATA-only inserts and tears every
row down in reverse-FK order in a finally block — even on failure.

Usage:
    # start server first, e.g. on port 8001:
    PYTHONPATH=$(pwd) python -m uvicorn app.main:app --port 8001
    # then:
    CAREVO_BASE=http://127.0.0.1:8001/api/v1 PYTHONPATH=$(pwd) python tests/test_carevo_skip.py

If pytest is available it will also be collected as test_carevo_skip_flow().
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import httpx
from jose import jwt
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.security import get_password_hash

BASE = os.environ.get("CAREVO_BASE", "http://127.0.0.1:8001/api/v1")

# Fixed ids -> exact teardown. Names carry the TEST_CAREVO_ marker.
ORG_ID = "aaaa0000-0000-0000-0000-0000000000a1"
OUTLET_ID = "aaaa0000-0000-0000-0000-0000000000b1"
MENU_ID = "aaaa0000-0000-0000-0000-0000000000c1"
CAT_ID = "aaaa0000-0000-0000-0000-0000000000d1"
ITEM_ID = "aaaa0000-0000-0000-0000-0000000000e1"          # available
ITEM_UNAVAIL_ID = "aaaa0000-0000-0000-0000-0000000000e2"  # is_available=false
STAFF_ID = "aaaa0000-0000-0000-0000-0000000000f1"

PHONE_A = "9700000001"   # main customer
PHONE_B = "9700000002"   # 2nd customer (owner-scope test)
PHONE_RL = "9700000009"  # rate-limit probe
ALL_PHONES = [PHONE_A, PHONE_B, PHONE_RL]

ITEM_PRICE = 250.00

_results: list[tuple[bool, str]] = []


def check(cond: bool, msg: str):
    _results.append((bool(cond), msg))
    print(("  PASS " if cond else "  FAIL ") + msg)


# --------------------------------------------------------------------------- #
async def seed():
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO organizations (id, name, created_at) VALUES (:id,'TEST_CAREVO_Org', now())"), {"id": ORG_ID})
        await c.execute(text("""
            INSERT INTO outlets (id, location_name, city, latitude, longitude, geofence_radius_meters, organization_id, created_at)
            VALUES (:id,'TEST_CAREVO_Outlet','Bengaluru', 12.9716, 77.5946, 200, :org, now())
        """), {"id": OUTLET_ID, "org": ORG_ID})
        await c.execute(text("INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) VALUES (:id,:o,'v1',true, now())"), {"id": MENU_ID, "o": OUTLET_ID})
        await c.execute(text("INSERT INTO categories (id, menu_id, name, created_at) VALUES (:id,:m,'TEST_CAREVO_Mains', now())"), {"id": CAT_ID, "m": MENU_ID})
        await c.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg, is_active, is_available, prep_time_minutes, tags, created_at)
            VALUES (:id,:c,'TEST_CAREVO_Paneer', :p, true, true, true, 12, '["chef-special"]'::json, now())
        """), {"id": ITEM_ID, "c": CAT_ID, "p": ITEM_PRICE})
        await c.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg, is_active, is_available, prep_time_minutes, tags, created_at)
            VALUES (:id,:c,'TEST_CAREVO_SoldOut', 99.00, true, true, false, 5, '[]'::json, now())
        """), {"id": ITEM_UNAVAIL_ID, "c": CAT_ID})
        await c.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)
            VALUES (:id,'TEST_CAREVO_staff', :pw, true, :o, now())
        """), {"id": STAFF_ID, "pw": get_password_hash("staffpin"), "o": OUTLET_ID})
    print("[seed] done")


async def teardown():
    async with engine.begin() as c:
        # reverse-FK order, scoped to our fixture rows only
        await c.execute(text("""
            DELETE FROM payment_transactions WHERE customer_order_id IN
              (SELECT id FROM customer_orders WHERE outlet_id = :o)
        """), {"o": OUTLET_ID})
        await c.execute(text("""
            DELETE FROM customer_order_items WHERE customer_order_id IN
              (SELECT id FROM customer_orders WHERE outlet_id = :o)
        """), {"o": OUTLET_ID})
        await c.execute(text("DELETE FROM customer_orders WHERE outlet_id = :o"), {"o": OUTLET_ID})
        await c.execute(text("DELETE FROM customers WHERE phone_number = ANY(:ph)"), {"ph": ALL_PHONES})
        await c.execute(text("DELETE FROM menu_items WHERE category_id = :c"), {"c": CAT_ID})
        await c.execute(text("DELETE FROM categories WHERE id = :i"), {"i": CAT_ID})
        await c.execute(text("DELETE FROM menus WHERE id = :i"), {"i": MENU_ID})
        await c.execute(text("DELETE FROM users WHERE id = :i"), {"i": STAFF_ID})
        await c.execute(text("DELETE FROM outlets WHERE id = :i"), {"i": OUTLET_ID})
        await c.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": ORG_ID})
    print("[teardown] done")


async def count_remaining() -> dict:
    async with engine.connect() as c:
        q = {
            "organizations": "SELECT count(*) FROM organizations WHERE name LIKE 'TEST_CAREVO_%'",
            "outlets": "SELECT count(*) FROM outlets WHERE location_name LIKE 'TEST_CAREVO_%'",
            "menus": "SELECT count(*) FROM menus WHERE id = :m",
            "categories": "SELECT count(*) FROM categories WHERE name LIKE 'TEST_CAREVO_%'",
            "menu_items": "SELECT count(*) FROM menu_items WHERE name LIKE 'TEST_CAREVO_%'",
            "users": "SELECT count(*) FROM users WHERE username LIKE 'TEST_CAREVO_%'",
            "customers": "SELECT count(*) FROM customers WHERE phone_number = ANY(:ph)",
            "customer_orders": "SELECT count(*) FROM customer_orders WHERE outlet_id = :o",
        }
        out = {}
        for k, sql in q.items():
            params = {}
            if ":m" in sql: params = {"m": MENU_ID}
            if ":ph" in sql: params = {"ph": ALL_PHONES}
            if ":o" in sql: params = {"o": OUTLET_ID}
            out[k] = (await c.execute(text(sql), params)).scalar()
        return out


async def db_order(order_id) -> dict:
    async with engine.connect() as c:
        row = (await c.execute(text(
            "SELECT status, payment_status, pickup_code, failed_attempts, is_locked FROM customer_orders WHERE id=:i"
        ), {"i": order_id})).first()
        return dict(zip(["status", "payment_status", "pickup_code", "failed_attempts", "is_locked"], row))


async def paid_txn_count(order_id) -> int:
    async with engine.connect() as c:
        return (await c.execute(text(
            "SELECT count(*) FROM payment_transactions WHERE customer_order_id=:i AND status='PAID'"
        ), {"i": order_id})).scalar()


# --------------------------------------------------------------------------- #
async def run():
    async with httpx.AsyncClient(timeout=30) as x:
        # ---- Case 1: request-otp -> verify-otp -> customer bearer w/ typ:customer
        print("\n[Case 1] OTP auth")
        r = await x.post(f"{BASE}/customer/auth/request-otp", json={"phone_number": PHONE_A})
        check(r.status_code == 200 and r.json().get("stub") is True, "request-otp 200 + stub")
        r = await x.post(f"{BASE}/customer/auth/verify-otp", json={"phone_number": PHONE_A, "otp": "000000"})
        check(r.status_code == 200, "verify-otp(000000) 200")
        tokA = r.json()["access_token"]
        claims = jwt.decode(tokA, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        check(claims.get("typ") == "customer", "token carries typ:customer")
        custA = {"Authorization": f"Bearer {tokA}"}
        r = await x.post(f"{BASE}/customer/auth/verify-otp", json={"phone_number": PHONE_A, "otp": "111111"})
        check(r.status_code == 401, "verify-otp wrong code -> 401")

        # ---- Case 2: OTP rate limit (>5/hr -> 429)
        print("\n[Case 2] OTP rate limit")
        codes = []
        for _ in range(6):
            rr = await x.post(f"{BASE}/customer/auth/request-otp", json={"phone_number": PHONE_RL})
            codes.append(rr.status_code)
        limit = settings.OTP_RATE_LIMIT_PER_HOUR
        check(codes[:limit] == [200] * limit and codes[limit] == 429,
              f"first {limit} ok then 429 (codes={codes}, limit={limit})")

        # ---- Case 3: outlets + menu (menu excludes is_available=false)
        print("\n[Case 3] discovery + menu")
        r = await x.get(f"{BASE}/customer/outlets", params={"lat": 12.97, "lng": 77.59}, headers=custA)
        outlets = r.json()
        check(r.status_code == 200 and any(str(o["id"]) == OUTLET_ID for o in outlets), "seeded outlet listed")
        seeded = next((o for o in outlets if str(o["id"]) == OUTLET_ID), {})
        check(seeded.get("distance_km") is not None, "distance_km computed when lat/lng given")
        r = await x.get(f"{BASE}/customer/menu/{OUTLET_ID}", headers=custA)
        menu = r.json()
        names = [it["name"] for cat in menu.get("categories", []) for it in cat["items"]]
        check(r.status_code == 200 and "TEST_CAREVO_Paneer" in names, "menu returns available item")
        check("TEST_CAREVO_SoldOut" not in names, "menu EXCLUDES is_available=false item")

        # ---- Case 4: create order (server-side total + razorpay-shaped gateway order)
        print("\n[Case 4] create order")
        r = await x.post(f"{BASE}/customer/orders", headers=custA, json={
            "outlet_id": OUTLET_ID,
            "items": [{"menu_item_id": ITEM_ID, "quantity": 2}],
            "customer_notes": "no onion",
        })
        check(r.status_code == 200, "create order 200")
        body = r.json()
        order_main = body["id"]
        check(body["total_amount"] == ITEM_PRICE * 2, f"total computed server-side (2x{ITEM_PRICE})")
        check(body["payment"]["gateway_order_id"].startswith("order_"), "razorpay-shaped gateway_order_id")
        check(body["payment"]["amount"] == int(ITEM_PRICE * 2 * 100), "gateway amount in paise")
        dbo = await db_order(order_main)
        check(dbo["status"] == "CREATED" and dbo["payment_status"] == "PENDING", "order CREATED/PENDING pre-payment")

        # ---- Case 5a: simulate payment -> PAID + 6-char pickup_code, idempotent
        print("\n[Case 5] payment (simulate + webhook)")
        r = await x.post(f"{BASE}/customer/payment/simulate", headers=custA, json={"order_id": order_main, "method": "upi"})
        check(r.status_code == 200 and r.json()["status"] == "PAID", "simulate -> PAID")
        pc1 = r.json()["pickup_code"]
        check(bool(pc1) and len(pc1) == 6, f"pickup_code 6 chars ({pc1})")
        r = await x.post(f"{BASE}/customer/payment/simulate", headers=custA, json={"order_id": order_main, "method": "upi"})
        check(r.status_code == 200 and r.json()["pickup_code"] == pc1, "simulate idempotent (same pickup_code)")
        check(await paid_txn_count(order_main) == 1, "no duplicate PAID transaction after re-simulate")

        # ---- Case 5b: real webhook path with stub-signed payload
        r = await x.post(f"{BASE}/customer/orders", headers=custA, json={
            "outlet_id": OUTLET_ID, "items": [{"menu_item_id": ITEM_ID, "quantity": 1}]})
        order_wh = r.json()["id"]
        gw_pay_id = "pay_" + uuid.uuid4().hex[:16]
        payload = {"event": "payment.captured", "order_id": order_wh,
                   "payload": {"payment": {"entity": {"id": gw_pay_id, "method": "card"}}}}
        # webhook secret unset -> stub gateway accepts any signature; send one anyway
        r = await x.post(f"{BASE}/customer/payment/webhook", json=payload,
                         headers={"X-Razorpay-Signature": "stub_sig"})
        check(r.status_code == 200 and r.json().get("status") == "PAID", "webhook -> PAID")
        pcw = r.json().get("pickup_code")
        check(bool(pcw) and len(pcw) == 6, f"webhook pickup_code 6 chars ({pcw})")
        check(await paid_txn_count(order_wh) == 1, "webhook produced exactly one PAID txn")

        # ---- Case 6: get order shows pickup_code + owner-scoped
        print("\n[Case 6] get order + owner scope")
        r = await x.get(f"{BASE}/customer/orders/{order_main}", headers=custA)
        check(r.status_code == 200 and r.json()["pickup_code"] == pc1, "owner sees pickup_code")
        # second customer
        r = await x.post(f"{BASE}/customer/auth/verify-otp", json={"phone_number": PHONE_B, "otp": "000000"})
        custB = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await x.get(f"{BASE}/customer/orders/{order_main}", headers=custB)
        check(r.status_code in (403, 404), f"other customer blocked ({r.status_code})")

        # ---- Case 7: staff verify-pickup
        print("\n[Case 7] staff verify-pickup")
        from app.core.auth import create_access_token
        staff = {"Authorization": f"Bearer {create_access_token(subject=STAFF_ID)}"}

        # 7a: correct code on PAID order -> verified + COMPLETED
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff,
                         json={"order_id": order_main, "pickup_code": pc1})
        j = r.json()
        check(r.status_code == 200 and j.get("verified") is True and j.get("status") == "COMPLETED",
              "correct code -> verified + COMPLETED")
        check((await db_order(order_main))["status"] == "COMPLETED", "order COMPLETED in DB")

        # 7b: customer token rejected on staff route -> 401
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=custA,
                         json={"order_id": order_wh, "pickup_code": pcw})
        check(r.status_code == 401, f"customer token rejected on staff route ({r.status_code})")

        # 7c: wrong code x3 -> attempts_remaining 2,1,0 then locked; 4th (correct) -> 423
        wrong = "000000" if pcw != "000000" else "ZZZZZZ"
        expected_remaining = [2, 1, 0]
        for i in range(3):
            r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff,
                             json={"order_id": order_wh, "pickup_code": wrong})
            j = r.json()
            check(j.get("verified") is False and j.get("attempts_remaining") == expected_remaining[i],
                  f"wrong attempt {i+1}: attempts_remaining={expected_remaining[i]}")
            if i == 2:
                check(j.get("locked") is True, "locked after 3rd wrong attempt")
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff,
                         json={"order_id": order_wh, "pickup_code": pcw})
        check(r.status_code == 423, f"locked order -> 423 even with correct code ({r.status_code})")
        check((await db_order(order_wh))["is_locked"] is True, "order is_locked=true in DB")

        # ---- Case 8: WS broadcast (light check)
        print("\n[Case 8] WS broadcast (light)")
        # A paid/advance transition calls CarevoService._broadcast_status via the
        # in-memory managers. We can't easily observe the fan-out over HTTP without a
        # live socket subscriber, but we verify the advance transition (which also
        # broadcasts) succeeds end-to-end without error, exercising that code path.
        r = await x.post(f"{BASE}/customer/orders", headers=custA, json={
            "outlet_id": OUTLET_ID, "items": [{"menu_item_id": ITEM_ID, "quantity": 1}]})
        order_ws = r.json()["id"]
        await x.post(f"{BASE}/customer/payment/simulate", headers=custA, json={"order_id": order_ws, "method": "upi"})
        r = await x.post(f"{BASE}/customer/orders/{order_ws}/advance", headers=staff, json={"status": "PREPARING"})
        check(r.status_code == 200 and r.json()["status"] == "PREPARING",
              "advance -> PREPARING (broadcast path executes without error)")


async def _main():
    await teardown()  # start clean (in case a prior run aborted)
    await seed()
    try:
        await run()
    finally:
        await teardown()
        remaining = await count_remaining()
        print("\n[teardown-proof] TEST_CAREVO_ rows remaining:", remaining)
        assert all(v == 0 for v in remaining.values()), f"LEFTOVER FIXTURES: {remaining}"
        await engine.dispose()

    passed = sum(1 for ok, _ in _results if ok)
    failed = [m for ok, m in _results if not ok]
    print(f"\n==== {passed}/{len(_results)} checks passed ====")
    if failed:
        print("FAILURES:")
        for m in failed:
            print("  -", m)
    return not failed


def test_carevo_skip_flow():
    """pytest entry point (also runnable as a script)."""
    assert asyncio.run(_main())


if __name__ == "__main__":
    ok = asyncio.run(_main())
    raise SystemExit(0 if ok else 1)
