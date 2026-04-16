# -*- coding: utf-8 -*-
"""Generate QR codes for zone-based tables.

Usage: cd backend && python generate_zone_qr.py
Requires: pip install qrcode requests pillow
"""
import requests
import os

try:
    import qrcode
except ImportError:
    print("Install qrcode: pip install qrcode[pil]")
    exit(1)

PC_IP = '192.168.1.4'
OUTLET_ID = '0b8a8349-6144-41a8-b028-b9089bd8eaea'
os.makedirs('qr_codes', exist_ok=True)

table_zones = {
    'T-1': 'normal', 'T-2': 'normal', 'T-3': 'normal',
    'T-4': 'normal', 'T-5': 'normal',
    'T-6': 'fine_dine', 'T-7': 'fine_dine', 'T-8': 'fine_dine',
    'T-9': 'fine_dine', 'T-10': 'fine_dine',
}

for table, zone in table_zones.items():
    r = requests.post(
        'http://127.0.0.1:8000/api/v1/tables/open',
        json={'outlet_id': OUTLET_ID, 'table_id': table, 'zone': zone}
    )
    token = r.json().get('token', '')
    url = f'http://{PC_IP}:3000/menu/{token}'

    img = qrcode.make(url)
    img.save(f'qr_codes/{table}_{zone}.png')
    print(f'{table} [{zone}] -> {url}')

print('Done! Check qr_codes folder')
