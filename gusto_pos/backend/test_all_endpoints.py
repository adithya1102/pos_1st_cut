"""Verify all 5 endpoints that were fixed."""
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

BASE = "http://127.0.0.1:8002/api/v1"

ORG_ID  = "4e1602de-0211-459b-ae4f-b759c512e4e7"
OUT_ID  = "cfba2bae-7b19-4a79-ad69-b5cda4a559d2"
MENU_ID = "ed22052e-ecf3-4758-acdb-05db91f457c3"

def api(method, path, body=None, headers=None, form_data=None):
    hdrs = headers or {}
    data = None
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    elif form_data is not None:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(form_data).encode()
    req = Request(f"{BASE}{path}", data=data, headers=hdrs, method=method)
    try:
        resp = urlopen(req)
        return resp.status, json.loads(resp.read().decode())
    except HTTPError as e:
        return e.code, e.read().decode()

print("=" * 60)
print("ENDPOINT VERIFICATION REPORT")
print("=" * 60)

# ---- Endpoint 1: POST /menus/categories/ ----
status1, body1 = api("POST", "/menus/categories/", {
    "name": "Verify Category",
    "display_order": 99,
    "menu_id": MENU_ID
})
cat_id = body1.get("id", "") if isinstance(body1, dict) else ""
result1 = "PASS" if status1 == 201 else "FAIL"
print(f"\n1. POST /menus/categories/  => {status1}  [{result1}]")
if status1 == 201:
    print(f"   Created category: {cat_id}")

# ---- Endpoint 2: POST /menus/items/ ----
status2, body2 = api("POST", "/menus/items/", {
    "name": "Verify Item",
    "base_price": 199.0,
    "category_id": cat_id
})
item_id = body2.get("id", "") if isinstance(body2, dict) else ""
result2 = "PASS" if status2 == 201 else "FAIL"
print(f"\n2. POST /menus/items/       => {status2}  [{result2}]")
if status2 == 201:
    print(f"   Created item: {item_id}")

# ---- Endpoint 3: GET /menus/{menu_id} (nested tree) ----
status3, body3 = api("GET", f"/menus/{MENU_ID}")
has_cats = isinstance(body3, dict) and "categories" in body3
has_items = False
if has_cats and body3["categories"]:
    has_items = "items" in body3["categories"][0]
result3 = "PASS" if status3 == 200 and has_cats and has_items else "FAIL"
print(f"\n3. GET /menus/{{menu_id}}    => {status3}  [{result3}]")
if isinstance(body3, dict):
    n_cats = len(body3.get("categories", []))
    n_items_total = sum(len(c.get("items", [])) for c in body3.get("categories", []))
    print(f"   Nested tree: {n_cats} categories, {n_items_total} items total")

# ---- Endpoint 4: POST /orders/ ----
status4, body4 = api("POST", "/orders/", {
    "outlet_id": OUT_ID,
    "total_amount": 0.0,
    "order_status": "pending"
})
order_id = body4.get("id", "") if isinstance(body4, dict) else ""
result4 = "PASS" if status4 == 201 else "FAIL"
print(f"\n4. POST /orders/            => {status4}  [{result4}]")
if status4 == 201:
    print(f"   Created order: {order_id}")

# ---- Endpoint 5: POST /auth/login ----
status5, body5 = api("POST", "/auth/login", form_data={
    "username": "adithya_owner",
    "password": "Test@1234"
})
has_token = isinstance(body5, dict) and "access_token" in body5
result5 = "PASS" if status5 == 200 and has_token else "FAIL"
print(f"\n5. POST /auth/login         => {status5}  [{result5}]")
if has_token:
    print(f"   Token: {body5['access_token'][:40]}...")

# ---- Summary ----
results = [result1, result2, result3, result4, result5]
passed = results.count("PASS")
print(f"\n{'=' * 60}")
print(f"RESULT: {passed}/5 endpoints passing")
print(f"{'=' * 60}")
