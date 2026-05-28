# Rudrarthi POS — Fix Summary & Test Report
_Generated: 2026-04-19_

---

## What Was Fixed

### 1. Backend (`backend/`)

| # | File | Fix |
|---|------|-----|
| 1a | `run_server.py` | Already correctly binding to `0.0.0.0:8000` — accessible over WiFi. No change needed. |
| 1b | `app/modules/menu/controller.py` | Updated `DEFAULT_CUSTOMIZATIONS` to include proper Indian restaurant options: No Ghee, No Oil, No Butter, Less Spicy, Extra Spicy, No Onion, No Garlic, Jain Style, Extra Cheese +₹25, Extra Butter +₹15. These are returned for every menu item in the zone endpoint. |
| 1c | `app/modules/orders/service.py` | Fixed hardcoded `OUTLET_ID` usage in `get_orders_by_table`, `settle_table`, and `generate_bill`. All three now accept an optional `outlet_id` parameter, defaulting to the Rudrarthi outlet UUID if not provided. |
| 1d | `app/modules/orders/controller.py` | Added optional `outlet_id` query parameter to `/table/{table_id}`, `/bill/{table_id}`, and `/settle/{table_id}` endpoints. Backward-compatible — existing clients without the param continue to work. |
| 1e | `seed_rudrarthi.sql` | Created full seed file (see §DB Setup below). |

**Bill PDF already had "RUDRARTHI" printed correctly** — no change needed there.

---

### 2. Customer App (`customer_app/`)

| # | File | Fix |
|---|------|-----|
| 2a | `lib/api.ts` | **Exported** `API_BASE` constant (was `const`, changed to `export const`) so other files can import it. Also updated default IP from `192.168.1.4` to `192.168.1.7`. |
| 2b | `.env.local` | Updated `NEXT_PUBLIC_API_URL` from `192.168.1.4:8000` to `192.168.1.7:8000`. |
| 2c | `app/menu/page.tsx` line 71 | Fixed broken URL `http://:8000/api/v1/tables/validate/${token}` → `${API_BASE}/api/v1/tables/validate/${token}`. |
| 2d | `app/menu/page.tsx` line 118 | Fixed broken URL `http://:8000/api/v1/menus/zone/...` → `${API_BASE}/api/v1/menus/zone/...`. |
| 2e | `app/menu/page.tsx` | Added `import { API_BASE } from '@/lib/api'` at top of file. |

**The customization popup, cart, and Proceed to Order button were already complete** — no changes needed.

---

### 3. Waiter App (`GustoWaiter/`)

| # | File | Fix |
|---|------|-----|
| 3a | `Views/DashboardPage.xaml` | Updated app title from `"GUSTO"` → `"RUDRARTHI"` in the header bar. |
| 3b | `ViewModels/ApprovalChecklistViewModel.cs` | Updated `PageTitle` from `"Table X — Approval Checklist"` → `"Rudrarthi · Table X — Checklist"`. |

**The waiter app already has full functionality implemented:**
- Dish tick/cross confirmation (via `CheckBox IsChecked="{Binding IsVerified, Mode=TwoWay}"`)
- "Approve & Send to Kitchen" button wired to `ApproveCommand` → `ApproveAsync()` → `_api.ConfirmOrderAsync()`
- Add Dish feature with search field and results list
- Remove dish button per item
- Grand total display of verified items
- API base URL already set to `http://192.168.1.7:8000` ✅

---

### 4. POS App (`GustoPOS/`)

| # | File | Fix |
|---|------|-----|
| 4a | `Services/ApiService.cs` | Fixed **broken** base URL `http://:8000/api/v1` → `http://192.168.1.7:8000/api/v1`. This was blocking ALL POS API calls. |
| 4b | `Views/MainPage.xaml` | Updated sidebar title from `"GUSTO"` → `"RUDRARTHI"`, subtitle from `"Rudrarthi"` → `"Restaurant POS"`. |

**The POS billing flow was already fully implemented:**
- Table grid with color-coded active/empty states
- Order listing per table with all dishes and totals
- "Generate Bill & Save PDF" → calls backend `/orders/bill/{tableId}` → saves PDF, shows amount
- "Settle & Close Table" → calls `/orders/settle/{tableId}` → marks all orders paid, refreshes table list
- Completed/settled orders disappear from the active screen (filtered by `order_status != 'paid'`)

---

## URLs for Testing

| Service | URL | Notes |
|---------|-----|-------|
| Backend API | `http://192.168.1.7:8000/docs` | FastAPI Swagger UI — verify all endpoints |
| Customer App | `http://192.168.1.7:3000/menu?outlet_id=0b8a8349-6144-41a8-b028-b9089bd8eaea&table_id=N-1&zone=normal` | Direct access without QR scan |
| Customer App (AC) | `http://192.168.1.7:3000/menu?outlet_id=0b8a8349-6144-41a8-b028-b9089bd8eaea&table_id=A-1&zone=ac` | AC zone test |

---

## Step-by-Step Test Flow

### Before You Start — Manual Setup (Required Once)

1. **Install PostgreSQL** and ensure it's running on localhost:5432
2. **Create the database:**
   ```
   psql -U postgres -c "CREATE DATABASE gusto_pos;"
   ```
3. **Run the schema** (creates all tables):
   ```
   psql -U postgres -d gusto_pos -f backend/schema.sql
   ```
4. **Run the seed data** (creates Rudrarthi outlet + menu + items):
   ```
   psql -U postgres -d gusto_pos -f backend/seed_rudrarthi.sql
   ```
5. **Install Python dependencies:**
   ```
   cd backend
   pip install -r requirements.txt
   ```
6. **Install Node dependencies for customer app:**
   ```
   cd customer_app
   npm install
   ```

### Starting the System

**Run as Administrator (right-click PowerShell → Run as Administrator):**

1. **Start Backend:**
   ```
   cd backend
   python run_server.py
   ```
   Verify: `http://192.168.1.7:8000/docs` loads in browser.

2. **Start Customer App:**
   ```
   cd customer_app
   npm run dev
   ```
   Verify: `http://192.168.1.7:3000` loads in browser.

3. **Start Waiter App (GustoWaiter):** Build and run from Visual Studio or:
   ```
   dotnet run --project GustoWaiter
   ```

4. **Start POS App (GustoPOS):** Build and run from Visual Studio or:
   ```
   dotnet run --project GustoPOS
   ```

### Full End-to-End Test Flow

**1. Customer orders:**
- Open `http://192.168.1.7:3000/menu?outlet_id=0b8a8349-6144-41a8-b028-b9089bd8eaea&table_id=N-3&zone=normal`
- Menu should load with categories: Starters, Main Course, Breads, Rice & Biryani, Beverages
- Tap any dish → customization popup appears with checkboxes (No Ghee, Less Spicy, Extra Cheese +₹25, etc.)
- Select some options → "Add to Order" adds to cart
- Add multiple dishes → tap the cart bar → Cart page shows all items
- "Confirm Order 🛎️" → success screen with order number

**2. Waiter app receives the order:**
- Waiter app shows a red notification badge
- Tap "🔔 Alerts" tab → order card for Table N-3 appears
- Tap the card → Approval Checklist page opens
- Title shows "Rudrarthi · Table N-3 — Checklist"
- Each dish has a checkbox — tick the ones to confirm
- Optionally search for an additional dish → tap to add it
- "✅ Approve & Send to Kitchen" → confirms order; waiter navigates back

**3. POS generates bill:**
- Open GustoPOS → sidebar shows "RUDRARTHI"
- Click "💰 Billing Center"
- Find table N-3 (highlighted in green = has orders)
- Click N-3 → right panel shows all dishes with quantities and totals
- Click "Generate Bill & Save PDF" → PDF saved, total displayed
- "Settle & Close Table" → table status resets to white (no orders)
- Table N-3 no longer appears as active

---

## Key IDs (For Reference)

| Resource | UUID |
|----------|------|
| Outlet (Rudrarthi) | `0b8a8349-6144-41a8-b028-b9089bd8eaea` |
| Menu (v1, is_latest=true) | `dc88b6a6-129c-479f-8609-07b8525f4310` |

---

## Remaining Manual Steps (Post-Setup)

1. **DLL lock on startup:** If GustoWaiter fails to build, kill it first: Task Manager → find `GustoWaiter.exe` → End Task.
2. **Elevation errors:** Always run PowerShell / scripts as Administrator.
3. **DB not initialized:** Run `schema.sql` then `seed_rudrarthi.sql` as documented above.
4. **Table open/close:** The customer app accesses menus via `outlet_id + table_id` query params. For QR-code flow, the waiter needs to "open" a table first via the Tables tab so a token is generated for the QR code.
5. **PDF viewer:** Bills are saved to `backend/bills/`. Ensure a PDF viewer (e.g. Adobe Reader) is installed so GustoPOS can open generated bills automatically.
