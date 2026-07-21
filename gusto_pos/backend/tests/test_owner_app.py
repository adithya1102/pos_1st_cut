"""
Gusto Owner App — functional test suite (Part 2 of the QA task).

Covers the newly-added staff-authed /pos/* Owner App endpoints:
  1. Outlet visibility toggle -> customer discovery (+ cross-outlet 403)
  2. notify item_unavailable line-item validation (422 / 400 / 200)
  3. notify reaches the correct customer WS session (+ isolation)
  4. verify-pickup lockout still returns 423
  5. per-dish availability toggle -> customer menu (+ /pos feeds are name-free)
  plus: every /pos/* route rejects a customer bearer (401) and no-auth (401/403).

Runs against a LIVE server (WS + in-memory managers live in the server process).
Seeds a self-contained, clearly-marked (TEST_CAREVO_) fixture set via DATA-only
inserts (fixed ids) and tears every row down in reverse-FK order in a finally
block — even on failure. NEVER touches pre-existing rows; NEVER runs DDL.

Usage:
    # start server first, e.g. on port 8010:
    PYTHONPATH=$(pwd) python -m uvicorn app.main:app --port 8010
    # then:
    OWNER_BASE=http://127.0.0.1:8010/api/v1 PYTHONPATH=$(pwd) python tests/test_owner_app.py

If pytest is available it is also collected as test_owner_app_flow().
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import websockets
from sqlalchemy import text

from app.core.auth import create_access_token
from app.core.database import engine
from app.core.security import get_password_hash
from app.modules.carevo_customer.deps import create_customer_token

BASE = os.environ.get("OWNER_BASE", "http://127.0.0.1:8010/api/v1")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://").rsplit("/api/v1", 1)[0]

# Fixed ids -> exact teardown. All identifying text carries TEST_CAREVO_.
ORG_ID = "bbbb0000-0000-0000-0000-0000000000a1"
OUTLET_ID = "bbbb0000-0000-0000-0000-0000000000b1"
OTHER_OUTLET_ID = "bbbb0000-0000-0000-0000-0000000000b9"  # not seeded; used for 403
MENU_ID = "bbbb0000-0000-0000-0000-0000000000c1"
CAT_ID = "bbbb0000-0000-0000-0000-0000000000d1"
ITEM1_ID = "bbbb0000-0000-0000-0000-0000000000e1"
ITEM2_ID = "bbbb0000-0000-0000-0000-0000000000e2"
STAFF_ID = "bbbb0000-0000-0000-0000-0000000000f1"
CUST_ID = "bbbb0000-0000-0000-0000-000000000a11"
ORDER_NOTIFY_ID = "bbbb0000-0000-0000-0000-000000000c01"  # has 2 line items
LINE1_ID = "bbbb0000-0000-0000-0000-000000000d01"
LINE2_ID = "bbbb0000-0000-0000-0000-000000000d02"
ORDER_LOCK_ID = "bbbb0000-0000-0000-0000-000000000c02"   # PAID, for lockout
LINE3_ID = "bbbb0000-0000-0000-0000-000000000d03"

PHONE = "9700000771"
ITEM1_NAME = "TEST_CAREVO_Dosa"
ITEM2_NAME = "TEST_CAREVO_Idli"
ITEM1_PRICE = 120.00
ITEM2_PRICE = 60.00
LOCK_PICKUP = "PICK99"

_results: list[tuple[bool, str]] = []


def check(cond: bool, msg: str):
    _results.append((bool(cond), msg))
    print(("  PASS " if cond else "  FAIL ") + msg)


# --------------------------------------------------------------------------- #
async def seed():
    async with engine.begin() as c:
        await c.execute(text("INSERT INTO organizations (id, name, created_at) VALUES (:id,'TEST_CAREVO_OwnerOrg', now())"), {"id": ORG_ID})
        await c.execute(text("""
            INSERT INTO outlets (id, location_name, city, latitude, longitude, geofence_radius_meters, organization_id, is_visible, created_at)
            VALUES (:id,'TEST_CAREVO_OwnerOutlet','Bengaluru', 12.9716, 77.5946, 200, :org, true, now())
        """), {"id": OUTLET_ID, "org": ORG_ID})
        await c.execute(text("INSERT INTO menus (id, outlet_id, version_label, is_latest, created_at) VALUES (:id,:o,'v1',true, now())"), {"id": MENU_ID, "o": OUTLET_ID})
        await c.execute(text("INSERT INTO categories (id, menu_id, name, created_at) VALUES (:id,:m,'TEST_CAREVO_OwnerCat', now())"), {"id": CAT_ID, "m": MENU_ID})
        await c.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg, is_active, is_available, prep_time_minutes, created_at)
            VALUES (:id,:c,:n,:p, true, true, true, 10, now())
        """), {"id": ITEM1_ID, "c": CAT_ID, "n": ITEM1_NAME, "p": ITEM1_PRICE})
        await c.execute(text("""
            INSERT INTO menu_items (id, category_id, name, base_price, is_veg, is_active, is_available, prep_time_minutes, created_at)
            VALUES (:id,:c,:n,:p, true, true, true, 8, now())
        """), {"id": ITEM2_ID, "c": CAT_ID, "n": ITEM2_NAME, "p": ITEM2_PRICE})
        await c.execute(text("""
            INSERT INTO users (id, username, hashed_password, is_active, outlet_id, created_at)
            VALUES (:id,'TEST_CAREVO_owner', :pw, true, :o, now())
        """), {"id": STAFF_ID, "pw": get_password_hash("ownerpin"), "o": OUTLET_ID})
        await c.execute(text("INSERT INTO customers (id, name, phone_number, created_at) VALUES (:id,'TEST_CAREVO_Cust',:ph, now())"), {"id": CUST_ID, "ph": PHONE})
        # notify order (live) with two line items
        await c.execute(text("""
            INSERT INTO customer_orders (id, customer_id, outlet_id, status, total_amount, payment_status, created_at, updated_at)
            VALUES (:id,:cu,:o,'RECEIVED',:t,'PAID', now(), now())
        """), {"id": ORDER_NOTIFY_ID, "cu": CUST_ID, "o": OUTLET_ID, "t": ITEM1_PRICE + ITEM2_PRICE})
        await c.execute(text("""
            INSERT INTO customer_order_items (id, customer_order_id, menu_item_id, name_snap, price_snap, quantity, created_at)
            VALUES (:id,:oid,:mi,:n,:p,1, now())
        """), {"id": LINE1_ID, "oid": ORDER_NOTIFY_ID, "mi": ITEM1_ID, "n": ITEM1_NAME, "p": ITEM1_PRICE})
        await c.execute(text("""
            INSERT INTO customer_order_items (id, customer_order_id, menu_item_id, name_snap, price_snap, quantity, created_at)
            VALUES (:id,:oid,:mi,:n,:p,2, now())
        """), {"id": LINE2_ID, "oid": ORDER_NOTIFY_ID, "mi": ITEM2_ID, "n": ITEM2_NAME, "p": ITEM2_PRICE})
        # lockout order (PAID w/ known pickup_code)
        await c.execute(text("""
            INSERT INTO customer_orders (id, customer_id, outlet_id, status, total_amount, payment_status, pickup_code, failed_attempts, is_locked, created_at, updated_at)
            VALUES (:id,:cu,:o,'PAID',:t,'PAID',:pc,0,false, now(), now())
        """), {"id": ORDER_LOCK_ID, "cu": CUST_ID, "o": OUTLET_ID, "t": ITEM1_PRICE, "pc": LOCK_PICKUP})
        await c.execute(text("""
            INSERT INTO customer_order_items (id, customer_order_id, menu_item_id, name_snap, price_snap, quantity, created_at)
            VALUES (:id,:oid,:mi,:n,:p,1, now())
        """), {"id": LINE3_ID, "oid": ORDER_LOCK_ID, "mi": ITEM1_ID, "n": ITEM1_NAME, "p": ITEM1_PRICE})
    print("[seed] done")


async def teardown():
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM payment_transactions WHERE customer_order_id IN (SELECT id FROM customer_orders WHERE outlet_id = :o)"), {"o": OUTLET_ID})
        await c.execute(text("DELETE FROM customer_order_items WHERE customer_order_id IN (SELECT id FROM customer_orders WHERE outlet_id = :o)"), {"o": OUTLET_ID})
        await c.execute(text("DELETE FROM customer_orders WHERE outlet_id = :o"), {"o": OUTLET_ID})
        await c.execute(text("DELETE FROM customers WHERE id = :i"), {"i": CUST_ID})
        await c.execute(text("DELETE FROM menu_items WHERE category_id = :c"), {"c": CAT_ID})
        await c.execute(text("DELETE FROM categories WHERE id = :i"), {"i": CAT_ID})
        await c.execute(text("DELETE FROM menus WHERE id = :i"), {"i": MENU_ID})
        await c.execute(text("DELETE FROM users WHERE id = :i"), {"i": STAFF_ID})
        await c.execute(text("DELETE FROM outlets WHERE id = :i"), {"i": OUTLET_ID})
        await c.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": ORG_ID})
    print("[teardown] done")


async def count_remaining() -> dict:
    async with engine.connect() as c:
        out = {}
        out["organizations"] = (await c.execute(text("SELECT count(*) FROM organizations WHERE id=:i"), {"i": ORG_ID})).scalar()
        out["outlets"] = (await c.execute(text("SELECT count(*) FROM outlets WHERE id=:i"), {"i": OUTLET_ID})).scalar()
        out["menus"] = (await c.execute(text("SELECT count(*) FROM menus WHERE id=:i"), {"i": MENU_ID})).scalar()
        out["categories"] = (await c.execute(text("SELECT count(*) FROM categories WHERE id=:i"), {"i": CAT_ID})).scalar()
        out["menu_items"] = (await c.execute(text("SELECT count(*) FROM menu_items WHERE category_id=:i"), {"i": CAT_ID})).scalar()
        out["users"] = (await c.execute(text("SELECT count(*) FROM users WHERE id=:i"), {"i": STAFF_ID})).scalar()
        out["customers"] = (await c.execute(text("SELECT count(*) FROM customers WHERE id=:i"), {"i": CUST_ID})).scalar()
        out["customer_orders"] = (await c.execute(text("SELECT count(*) FROM customer_orders WHERE outlet_id=:i"), {"i": OUTLET_ID})).scalar()
        return out


async def _recv_json(ws, timeout=5.0):
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _drain_connected(ws):
    """Consume the initial CONNECTED welcome frame."""
    msg = await _recv_json(ws)
    assert msg.get("event") == "CONNECTED", f"unexpected first frame: {msg}"


# --------------------------------------------------------------------------- #
async def run():
    staff = {"Authorization": f"Bearer {create_access_token(subject=STAFF_ID)}"}
    cust_tok = create_customer_token(CUST_ID)
    cust = {"Authorization": f"Bearer {cust_tok}"}

    async with httpx.AsyncClient(timeout=30) as x:
        # ---- Case 0: auth guards on /pos/* --------------------------------
        print("\n[Case 0] /pos/* auth guards")
        guard_calls = [
            ("get", "/pos/outlet", None),
            ("get", "/pos/menu-items", None),
            ("get", "/pos/orders", None),
            ("post", f"/pos/outlets/{OUTLET_ID}/visibility", {"is_visible": True}),
            ("patch", f"/pos/menu-items/{ITEM1_ID}/availability", {"is_available": True}),
            ("post", f"/pos/orders/{ORDER_NOTIFY_ID}/notify", {"type": "ready_now"}),
            ("post", "/pos/orders/verify-pickup", {"order_id": ORDER_LOCK_ID, "pickup_code": "x"}),
        ]
        cust_codes, noauth_codes = [], []
        for method, path, body in guard_calls:
            kw = {"json": body} if body is not None else {}
            r = await getattr(x, method)(f"{BASE}{path}", headers=cust, **kw)
            cust_codes.append(r.status_code)
            r = await getattr(x, method)(f"{BASE}{path}", **kw)
            noauth_codes.append(r.status_code)
        check(all(c == 401 for c in cust_codes), f"customer bearer rejected on all /pos/* (401) -> {cust_codes}")
        check(all(c in (401, 403) for c in noauth_codes), f"no-auth rejected on all /pos/* (401/403) -> {noauth_codes}")

        # ---- Case 1: visibility -> discovery ------------------------------
        print("\n[Case 1] outlet visibility -> customer discovery")
        r = await x.get(f"{BASE}/customer/outlets", headers=cust)
        present0 = any(str(o["id"]) == OUTLET_ID for o in r.json())
        check(r.status_code == 200 and present0, "outlet visible in discovery initially")

        r = await x.post(f"{BASE}/pos/outlets/{OUTLET_ID}/visibility", headers=staff, json={"is_visible": False})
        check(r.status_code == 200 and r.json()["is_visible"] is False, "set is_visible=false -> 200")
        r = await x.get(f"{BASE}/customer/outlets", headers=cust)
        absent = not any(str(o["id"]) == OUTLET_ID for o in r.json())
        check(absent, "outlet ABSENT from discovery when hidden")

        r = await x.post(f"{BASE}/pos/outlets/{OUTLET_ID}/visibility", headers=staff, json={"is_visible": True})
        check(r.status_code == 200 and r.json()["is_visible"] is True, "set is_visible=true -> 200")
        r = await x.get(f"{BASE}/customer/outlets", headers=cust)
        present = any(str(o["id"]) == OUTLET_ID for o in r.json())
        check(present, "outlet PRESENT again in discovery")

        r = await x.post(f"{BASE}/pos/outlets/{OTHER_OUTLET_ID}/visibility", headers=staff, json={"is_visible": False})
        check(r.status_code == 403, f"toggling another outlet -> 403 ({r.status_code})")

        # ---- Case 2: item_unavailable line-item validation ----------------
        print("\n[Case 2] notify item_unavailable validation")
        r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "item_unavailable"})
        check(r.status_code == 422, f"item_unavailable w/o item_id -> 422 ({r.status_code})")
        bogus_item = str(uuid.uuid4())
        r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "item_unavailable", "item_id": bogus_item})
        check(r.status_code == 400, f"item_unavailable w/ non-line item_id -> 400 ({r.status_code})")
        r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "item_unavailable", "item_id": LINE1_ID})
        j = r.json()
        check(r.status_code == 200 and j.get("item_name") == ITEM1_NAME,
              f"valid line item -> 200 & item_name=={ITEM1_NAME} ({r.status_code}/{j.get('item_name')})")

        # ---- Case 3: notify reaches the right WS session ------------------
        print("\n[Case 3] notify -> customer WS (+ isolation)")
        target_url = f"{WS_BASE}/ws/order/{ORDER_NOTIFY_ID}"
        other_order = str(uuid.uuid4())
        other_url = f"{WS_BASE}/ws/order/{other_order}"
        async with websockets.connect(target_url) as ws, websockets.connect(other_url) as ws_other:
            await _drain_connected(ws)
            await _drain_connected(ws_other)

            # ready_now
            r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "ready_now"})
            check(r.status_code == 200 and r.json().get("delivered") is True, "ready_now notify 200 + delivered")
            f1 = await _recv_json(ws)
            check(f1.get("event") == "notify" and f1.get("type") == "ready_now" and bool(f1.get("message")),
                  f"WS frame ready_now (event/type/message) -> {f1.get('type')}")

            # delayed_10
            r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "delayed_10"})
            f2 = await _recv_json(ws)
            check(f2.get("event") == "notify" and f2.get("type") == "delayed_10" and bool(f2.get("message")),
                  f"WS frame delayed_10 -> {f2.get('type')}")

            # item_unavailable(valid) -> item_name in frame
            r = await x.post(f"{BASE}/pos/orders/{ORDER_NOTIFY_ID}/notify", headers=staff, json={"type": "item_unavailable", "item_id": LINE2_ID})
            f3 = await _recv_json(ws)
            check(f3.get("event") == "notify" and f3.get("type") == "item_unavailable" and f3.get("item_name") == ITEM2_NAME,
                  f"WS frame item_unavailable item_name=={ITEM2_NAME} -> {f3.get('item_name')}")

            # isolation: the OTHER socket must not have received any notify
            got_leak = False
            try:
                leak = await _recv_json(ws_other, timeout=1.5)
                got_leak = leak.get("event") == "notify"
            except asyncio.TimeoutError:
                got_leak = False
            check(not got_leak, "different-order socket did NOT receive the notify (isolation)")

        # ---- Case 4: lockout still 423 ------------------------------------
        print("\n[Case 4] verify-pickup lockout -> 423")
        expected = [2, 1, 0]
        for i in range(3):
            r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff, json={"order_id": ORDER_LOCK_ID, "pickup_code": "WRONG0"})
            j = r.json()
            check(j.get("verified") is False and j.get("attempts_remaining") == expected[i],
                  f"wrong attempt {i+1}: attempts_remaining={expected[i]} (got {j.get('attempts_remaining')})")
            if i == 2:
                check(j.get("locked") is True, "locked after 3rd wrong attempt")
        r = await x.post(f"{BASE}/pos/orders/verify-pickup", headers=staff, json={"order_id": ORDER_LOCK_ID, "pickup_code": LOCK_PICKUP})
        check(r.status_code == 423, f"locked order -> 423 even with correct code ({r.status_code})")

        # ---- Case 5: dish availability toggle -----------------------------
        print("\n[Case 5] dish availability -> customer menu + name-free feeds")

        def menu_names(menu):
            return [it["name"] for cat in menu.get("categories", []) for it in cat["items"]]

        r = await x.get(f"{BASE}/customer/menu/{OUTLET_ID}", headers=cust)
        check(r.status_code == 200 and ITEM1_NAME in menu_names(r.json()), "item present in customer menu initially")

        r = await x.patch(f"{BASE}/pos/menu-items/{ITEM1_ID}/availability", headers=staff, json={"is_available": False})
        check(r.status_code == 200 and r.json()["is_available"] is False, "PATCH availability=false -> 200")
        r = await x.get(f"{BASE}/customer/menu/{OUTLET_ID}", headers=cust)
        check(ITEM1_NAME not in menu_names(r.json()), "item EXCLUDED from customer menu when unavailable")
        # /pos/menu-items reflects the flag
        r = await x.get(f"{BASE}/pos/menu-items", headers=staff)
        item_row = next((m for m in r.json() if str(m["id"]) == ITEM1_ID), None)
        check(item_row is not None and item_row["is_available"] is False, "/pos/menu-items shows is_available=false")

        r = await x.patch(f"{BASE}/pos/menu-items/{ITEM1_ID}/availability", headers=staff, json={"is_available": True})
        check(r.status_code == 200 and r.json()["is_available"] is True, "PATCH availability=true -> 200")
        r = await x.get(f"{BASE}/customer/menu/{OUTLET_ID}", headers=cust)
        check(ITEM1_NAME in menu_names(r.json()), "item INCLUDED again in customer menu")
        r = await x.get(f"{BASE}/pos/menu-items", headers=staff)
        item_row = next((m for m in r.json() if str(m["id"]) == ITEM1_ID), None)
        check(item_row is not None and item_row["is_available"] is True, "/pos/menu-items shows is_available=true")

        # /pos/orders is name-free (no customer name/phone leakage)
        r = await x.get(f"{BASE}/pos/orders", headers=staff)
        orders = r.json()
        blob = json.dumps(orders).lower()
        has_our_order = any(str(o["order_id"]) == ORDER_NOTIFY_ID for o in orders)
        no_phone = PHONE not in json.dumps(orders)
        no_cust_fields = ("phone" not in blob) and ("customer_name" not in blob) and ("customer_id" not in blob)
        check(r.status_code == 200 and has_our_order, "/pos/orders lists our active order")
        check(no_phone and no_cust_fields, "/pos/orders is NAME-FREE (no phone/customer fields)")


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


def test_owner_app_flow():
    """pytest entry point (also runnable as a script)."""
    assert asyncio.run(_main())


if __name__ == "__main__":
    ok = asyncio.run(_main())
    raise SystemExit(0 if ok else 1)
