"""
Gusto POS -- End-to-End Integration Test
Simulates the full flow across all three clients:
  [SYSTEM]   -> Table setup
  [CUSTOMER] -> Next.js customer app
  [WAITER]   -> MAUI Tablet
  [POS]      -> MAUI Desktop
"""

import sys
import requests

BASE_URL = "http://127.0.0.1:8000/api/v1"
TABLE_ID = "N-1"
ZONE = "normal"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(resp, label):
    if resp.status_code not in (200, 201):
        print(f"\n  FAILED: {label}")
        print(f"    Status : {resp.status_code}")
        try:
            print(f"    Body   : {resp.json()}")
        except Exception:
            print(f"    Body   : {resp.text}")
        sys.exit(1)
    return resp.json()


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


# ---------------------------------------------------------------------------
# STEP 1 -- SYSTEM: Table Setup
# ---------------------------------------------------------------------------
section("STEP 1 | [SYSTEM] Table Setup")

print(f"[SYSTEM] GET /outlets/ -- fetching outlet list...")
r = requests.get(f"{BASE_URL}/outlets/")
outlets = ok(r, "GET /outlets/")
assert len(outlets) > 0, "No outlets found in the database."

# Find the first outlet that has at least 2 items in the target zone menu
outlet = None
for candidate in outlets:
    probe = requests.get(f"{BASE_URL}/menus/zone/{candidate['id']}/{ZONE}")
    if probe.status_code == 200:
        cats = probe.json().get("categories", [])
        items = sum(len(c.get("items", [])) for c in cats)
        if items >= 2:
            outlet = candidate
            break

assert outlet is not None, (
    f"No outlet found with at least 2 available items in the '{ZONE}' zone. "
    "Ensure the DB has price_rules configured for at least one outlet."
)
outlet_id = outlet["id"]
print(f"[SYSTEM] PASS: Found outlet '{outlet.get('location_name', 'N/A')}' | id={outlet_id}")

print(f"[SYSTEM] POST /tables/open -- opening session for table '{TABLE_ID}', zone='{ZONE}'...")
r = requests.post(f"{BASE_URL}/tables/open", json={
    "outlet_id": outlet_id,
    "table_id": TABLE_ID,
    "zone": ZONE,
})
session = ok(r, "POST /tables/open")
session_token = session["token"]
assert session_token, "Session token is empty."
print(f"[SYSTEM] PASS: Session opened | token={session_token} | expires={session.get('expires_at', 'N/A')}")


# ---------------------------------------------------------------------------
# STEP 2 -- CUSTOMER: Next.js ordering flow
# ---------------------------------------------------------------------------
section("STEP 2 | [CUSTOMER] Next.js -- Browse Menu & Place Order")

print(f"[CUSTOMER] GET /menus/zone/{outlet_id}/{ZONE} -- loading menu...")
r = requests.get(f"{BASE_URL}/menus/zone/{outlet_id}/{ZONE}")
menu = ok(r, f"GET /menus/zone/{outlet_id}/{ZONE}")
categories = menu.get("categories", [])
assert len(categories) > 0, "Menu returned no categories."
print(f"[CUSTOMER] PASS: Menu loaded | {len(categories)} categories")

items_found = []
for cat in categories:
    for item in cat.get("items", []):
        if item.get("is_available", True) and item.get("price", 0) > 0:
            items_found.append({
                "id": item["id"],
                "name": item["name"],
                "price": item["price"],
            })
        if len(items_found) >= 2:
            break
    if len(items_found) >= 2:
        break

assert len(items_found) >= 2, (
    f"Need at least 2 available items in the '{ZONE}' zone menu, found {len(items_found)}. "
    "Check that price_rules exist for this outlet/zone."
)
item1, item2 = items_found[0], items_found[1]
print(f"[CUSTOMER] Item 1: '{item1['name']}' @ Rs.{item1['price']} (id={item1['id']})")
print(f"[CUSTOMER] Item 2: '{item2['name']}' @ Rs.{item2['price']} (id={item2['id']})")

total = round(item1["price"] * 1 + item2["price"] * 2, 2)
order_payload = {
    "outlet_id": outlet_id,
    "table_id": TABLE_ID,
    "total_amount": total,
    "order_status": "pending",
    "items": [
        {
            "name": item1["name"],
            "quantity": 1,
            "unit_price": item1["price"],
            "customizations": [],
        },
        {
            "name": item2["name"],
            "quantity": 2,
            "unit_price": item2["price"],
            "customizations": [],
        },
    ],
}
print(f"[CUSTOMER] POST /orders/ -- placing order (total=Rs.{total})...")
r = requests.post(f"{BASE_URL}/orders/", json=order_payload)
order = ok(r, "POST /orders/")
order_id = order["id"]
readable_id = order.get("readable_id", "N/A")
assert order_id, "Order ID missing from response."
assert order.get("order_status") == "pending", \
    f"Expected status 'pending', got '{order.get('order_status')}'"
print(f"[CUSTOMER] PASS: Order placed | order_id={order_id} | readable_id=#{readable_id} | status={order['order_status']}")


# ---------------------------------------------------------------------------
# STEP 3 -- WAITER: MAUI Tablet -- Review & Approve Order
# ---------------------------------------------------------------------------
section("STEP 3 | [WAITER] MAUI Tablet -- Review Queue & Approve Order")

print(f"[WAITER] GET /orders/ -- fetching order list...")
r = requests.get(f"{BASE_URL}/orders/")
all_orders = ok(r, "GET /orders/")
pending_for_outlet = [
    o for o in all_orders
    if str(o.get("outlet_id")) == str(outlet_id) and o.get("order_status") == "pending"
]
print(f"[WAITER] {len(pending_for_outlet)} pending order(s) found for this outlet")

our_order_in_queue = next(
    (o for o in pending_for_outlet if str(o["id"]) == str(order_id)), None
)
assert our_order_in_queue is not None, (
    f"Order {order_id} not found in pending queue. "
    f"Pending IDs: {[o['id'] for o in pending_for_outlet]}"
)
print(f"[WAITER] PASS: Order #{readable_id} is visible in the pending queue")

print(f"[WAITER] PUT /orders/{order_id} -- updating status to 'confirmed'...")
r = requests.put(f"{BASE_URL}/orders/{order_id}", json={"order_status": "confirmed"})
updated_order = ok(r, f"PUT /orders/{order_id}")
assert updated_order.get("order_status") == "confirmed", \
    f"Expected status 'confirmed', got '{updated_order.get('order_status')}'"
print(f"[WAITER] PASS: Order #{readable_id} approved | new status={updated_order['order_status']}")


# ---------------------------------------------------------------------------
# STEP 4 -- POS: MAUI Desktop -- Verify Table & Bill
# ---------------------------------------------------------------------------
section("STEP 4 | [POS] MAUI Desktop -- Verify Active Table & Bill")

print(f"[POS] GET /tables/active?outlet_id={outlet_id} -- fetching active tables...")
r = requests.get(f"{BASE_URL}/tables/active", params={"outlet_id": outlet_id})
active_tables = ok(r, "GET /tables/active")
table_n1 = next((t for t in active_tables if t.get("table_id") == TABLE_ID), None)
assert table_n1 is not None, (
    f"Table '{TABLE_ID}' not found in active sessions. "
    f"Active tables: {[t.get('table_id') for t in active_tables]}"
)
print(f"[POS] PASS: Table '{TABLE_ID}' is active | session_token={table_n1.get('token')}")

print(f"[POS] GET /orders/table/{TABLE_ID} -- fetching orders for table '{TABLE_ID}'...")
r = requests.get(f"{BASE_URL}/orders/table/{TABLE_ID}")
table_orders = ok(r, f"GET /orders/table/{TABLE_ID}")
confirmed_orders = [o for o in table_orders if o.get("order_status") == "confirmed"]
assert len(confirmed_orders) > 0, (
    f"No confirmed orders found for table '{TABLE_ID}'. "
    f"Statuses: {[o.get('order_status') for o in table_orders]}"
)
our_confirmed = next((o for o in confirmed_orders if str(o["id"]) == str(order_id)), None)
assert our_confirmed is not None, \
    f"Order {order_id} not found in confirmed state for table '{TABLE_ID}'."
print(f"[POS] PASS: Confirmed order #{readable_id} is present for table '{TABLE_ID}'")

actual_total = float(our_confirmed.get("total_amount", 0))
print(f"[POS] Verifying total: expected=Rs.{total}, stored=Rs.{actual_total}")
assert abs(actual_total - total) < 0.01, \
    f"Total mismatch! Expected Rs.{total}, got Rs.{actual_total}"
print(f"[POS] PASS: Total amount Rs.{actual_total} is correct")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("ALL STEPS PASSED")
print(f"  Outlet       : {outlet.get('location_name')} ({outlet_id})")
print(f"  Table        : {TABLE_ID} | Zone: {ZONE}")
print(f"  Session Token: {session_token}")
print(f"  Order ID     : #{readable_id} ({order_id})")
print(f"  Items Ordered: {item1['name']} x1 + {item2['name']} x2")
print(f"  Total        : Rs.{actual_total}")
print(f"  Final Status : {updated_order['order_status']}")
print()
