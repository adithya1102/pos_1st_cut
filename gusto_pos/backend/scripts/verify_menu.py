"""Verify the menu via API."""
import requests

r = requests.get("http://127.0.0.1:8000/api/v1/menus/dc88b6a6-129c-479f-8609-07b8525f4310")
data = r.json()
print(f"Status: {r.status_code}")
cats = data.get("categories", [])
print(f"Total Categories: {len(cats)}")
total = 0
for cat in cats:
    count = len(cat.get("items", []))
    total += count
    print(f"  {cat['name']}: {count} items")
print(f"Total Items: {total}")
