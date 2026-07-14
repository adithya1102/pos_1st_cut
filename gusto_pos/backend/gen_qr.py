import os
import requests
import qrcode

IP = "192.168.1.6"
OUTLET = "0b8a8349-6144-41a8-b028-b9089bd8eaea"
BASE = "http://127.0.0.1:8000/api/v1"

os.makedirs("qr_codes", exist_ok=True)

cfg = requests.get(f"{BASE}/config/{OUTLET}").json()
n = int(cfg.get("normal_table_count", 10))
a = int(cfg.get("ac_table_count", 4))

made = 0
for prefix, count, zone in (("N", n, "normal"), ("A", a, "ac")):
    for i in range(1, count + 1):
        t = f"{prefix}-{i}"
        r = requests.post(
            f"{BASE}/tables/open",
            json={"outlet_id": OUTLET, "table_id": t, "zone": zone},
        )
        token = r.json().get("token", "")
        if not token:
            print(f"{t} -> NO TOKEN ({r.status_code})")
            continue
        url = f"http://{IP}:3000/t/{token}"
        qrcode.make(url).save(f"qr_codes/{t}.png")
        print(f"{t} -> {url}")
        made += 1

print(f"{made} QR codes saved to backend/qr_codes/")
