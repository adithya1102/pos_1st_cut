"""Update customer app for zone support."""
import os

# ?? Update [slug]/page.tsx ??
slug_path = os.path.join('..', 'customer_app', 'app', 'menu', '[slug]', 'page.tsx')
with open(slug_path, 'r') as f:
    content = f.read()

# 1. Update goToMenu to include zone
old_go = "  const goToMenu = useCallback((oid: string, tid: string) => {\n    router.push(`/menu?outlet_id=${oid}&table_id=${tid}&token=${slug}`);\n  }, [router, slug]);"
new_go = "  // Zone state\n  const [zone, setZone] = useState('normal');\n\n  // Redirect helper — must include token so menu page can validate\n  const goToMenu = useCallback((oid: string, tid: string, z: string = 'normal') => {\n    router.push(`/menu?outlet_id=${oid}&table_id=${tid}&token=${slug}&zone=${z}`);\n  }, [router, slug]);"
content = content.replace(old_go, new_go)

# 2. After setting tableId/outletId, also store zone
old_valid = """        // Valid token
        setTableId(data.table_id);
        setOutletId(data.outlet_id);

        // ?? STEP B — Check existing session ??"""
new_valid = """        // Valid token
        setTableId(data.table_id);
        setOutletId(data.outlet_id);
        const tableZone = data.zone || 'normal';
        setZone(tableZone);
        localStorage.setItem('table_zone', tableZone);

        // ?? STEP B — Check existing session ??"""
content = content.replace(old_valid, new_valid)

# 3. Update goToMenu calls to pass zone
# In step B existing session redirect
content = content.replace(
    "              goToMenu(data.outlet_id, data.table_id);",
    "              goToMenu(data.outlet_id, data.table_id, tableZone);"
)

# In step D verify OTP - after confirmed
content = content.replace(
    "        goToMenu(outletId || OUTLET_ID, tableId);",
    "        goToMenu(outletId || OUTLET_ID, tableId, zone);"
)

# In step E poll for waiter confirmation
content = content.replace(
    "          goToMenu(outletId || OUTLET_ID, tableId);",
    "          goToMenu(outletId || OUTLET_ID, tableId, zone);"
)

with open(slug_path, 'w') as f:
    f.write(content)
print(f'Updated {slug_path}')


# ?? Update menu/page.tsx ??
menu_path = os.path.join('..', 'customer_app', 'app', 'menu', 'page.tsx')
with open(menu_path, 'r') as f:
    content = f.read()

# Replace the menu fetch logic to use zone-based endpoint
old_fetch = """  // Fetch menu (only if token is valid)
  useEffect(() => {
    if (tokenValid === false) {
      setLoading(false);
      return;
    }
    if (tokenValid === null) {
      // Still validating token
      return;
    }

    const menuId = searchParams.get('menu_id') || process.env.NEXT_PUBLIC_MENU_ID || '';
    setLoading(true);
    fetchMenu(menuId || undefined)
      .then((data) => {"""

new_fetch = """  // Fetch menu (only if token is valid)
  useEffect(() => {
    if (tokenValid === false) {
      setLoading(false);
      return;
    }
    if (tokenValid === null) {
      // Still validating token
      return;
    }

    const zone = searchParams.get('zone') || localStorage.getItem('table_zone') || 'normal';
    const outletId = searchParams.get('outlet_id') || process.env.NEXT_PUBLIC_OUTLET_ID || '';
    setLoading(true);
    fetch(`http://192.168.1.4:8000/api/v1/menus/by-zone/${outletId}/${zone}`)
      .then((res) => { if (!res.ok) throw new Error('Failed to fetch menu'); return res.json(); })
      .then((data) => {"""

content = content.replace(old_fetch, new_fetch)

with open(menu_path, 'w') as f:
    f.write(content)
print(f'Updated {menu_path}')
