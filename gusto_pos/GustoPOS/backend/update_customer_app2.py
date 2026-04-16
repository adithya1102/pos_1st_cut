# -*- coding: utf-8 -*-
"""Update customer app for zone support."""
import os

# Update [slug]/page.tsx
slug_path = os.path.join('..', 'customer_app', 'app', 'menu', '[slug]', 'page.tsx')
with open(slug_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add zone state and update goToMenu
old_go = "  // Redirect helper"
new_go = "  // Zone state\n  const [zone, setZone] = useState('normal');\n\n  // Redirect helper"
content = content.replace(old_go, new_go, 1)

old_push = "router.push(`/menu?outlet_id=${oid}&table_id=${tid}&token=${slug}`);"
new_push = "router.push(`/menu?outlet_id=${oid}&table_id=${tid}&token=${slug}&zone=${z}`);"
content = content.replace(old_push, new_push, 1)

old_sig = "const goToMenu = useCallback((oid: string, tid: string) => {"
new_sig = "const goToMenu = useCallback((oid: string, tid: string, z: string = 'normal') => {"
content = content.replace(old_sig, new_sig, 1)

# 2. After setOutletId, store zone
old_set = "        setOutletId(data.outlet_id);"
new_set = "        setOutletId(data.outlet_id);\n        const tableZone = data.zone || 'normal';\n        setZone(tableZone);\n        localStorage.setItem('table_zone', tableZone);"
content = content.replace(old_set, new_set, 1)

# 3. Update goToMenu calls to pass zone
# Step B: existing session redirect
content = content.replace(
    "goToMenu(data.outlet_id, data.table_id);",
    "goToMenu(data.outlet_id, data.table_id, tableZone);",
    1
)

# Step D: after OTP confirmed
content = content.replace(
    "goToMenu(outletId || OUTLET_ID, tableId);",
    "goToMenu(outletId || OUTLET_ID, tableId, zone);",
    1
)

# Step E: poll redirect (same pattern)
content = content.replace(
    "goToMenu(outletId || OUTLET_ID, tableId);",
    "goToMenu(outletId || OUTLET_ID, tableId, zone);",
    1
)

with open(slug_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'Updated {slug_path}')


# Update menu/page.tsx
menu_path = os.path.join('..', 'customer_app', 'app', 'menu', 'page.tsx')
with open(menu_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace menu fetch: from fetchMenu to zone-based fetch
old_fetch = "    const menuId = searchParams.get('menu_id') || process.env.NEXT_PUBLIC_MENU_ID || '';\n    setLoading(true);\n    fetchMenu(menuId || undefined)\n      .then((data) => {"
new_fetch = "    const zone = searchParams.get('zone') || localStorage.getItem('table_zone') || 'normal';\n    const outletIdForMenu = searchParams.get('outlet_id') || process.env.NEXT_PUBLIC_OUTLET_ID || '';\n    setLoading(true);\n    fetch(`http://192.168.1.2:8000/api/v1/menus/by-zone/${outletIdForMenu}/${zone}`)\n      .then((res) => { if (!res.ok) throw new Error('Failed to fetch menu'); return res.json(); })\n      .then((data) => {"
content = content.replace(old_fetch, new_fetch, 1)

with open(menu_path, 'w', encoding='utf-8') as f:
    f.write(content)
print(f'Updated {menu_path}')
