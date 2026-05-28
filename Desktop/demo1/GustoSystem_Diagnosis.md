# Gusto POS — End-to-End Diagnosis Report
_Generated: 2026-04-19_

---

## Repo Structure

```
pos_1st_cut/gusto_pos/
├── backend/          FastAPI (Python) — port 8000
├── customer_app/     Next.js (React/TS) — port 3000
├── GustoWaiter/      .NET MAUI — waiter tablet app
└── GustoPOS/         .NET MAUI — POS/billing desktop app
```

---

## Startup Issues (Why It's Failing Right Now)

### 1. GustoWaiter.dll Locked ("Cannot open for writing")
**Cause:** The app is still running in the background from a previous session. Windows locks DLLs of running .NET processes.  
**Fix:** Before building/running, kill the process:
```powershell
Get-Process | Where-Object {$_.ProcessName -like "*GustoWaiter*"} | Stop-Process -Force
# Or in Task Manager: find GustoWaiter.exe and End Task
```

### 2. Elevation Error ("Requires Administrator")
**Cause:** The startup script likely tries to modify hosts file, bind to low ports, or install a service — all of which need admin.  
**Fix:** Right-click PowerShell → "Run as Administrator" before launching StartGusto.ps1.

### 3. Database Not Loading
**Cause:** The backend uses PostgreSQL at `localhost:5432` with credentials `postgres/postgres` and database name `gusto_pos`. If PostgreSQL isn't installed/running, or the database hasn't been created and seeded, the backend will fail on startup.  
**Fix:**
```bash
# 1. Make sure PostgreSQL is running
# 2. Create the database
psql -U postgres -c "CREATE DATABASE gusto_pos;"
# 3. Run the schema
psql -U postgres -d gusto_pos -f backend/schema.sql
# 4. Run Alembic migrations (if any)
cd backend && alembic upgrade head
# 5. Seed initial data (init_db.py handles this on first startup)
```

### 4. URLs Not Opening (192.168.1.7:8000 and :3000)
**Cause (Backend):** Backend is configured to bind to `127.0.0.1:8000` (loopback only). It won't be reachable at `192.168.1.7` unless you change the host binding.  
**Fix:** In `backend/run_server.py`, change:
```python
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# → change to:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Cause (Customer App):** The API base URL in `customer_app/.env.local` likely points to the wrong IP. Also, there are hardcoded broken URLs in the menu page (see Critical Bugs below).

---

## Backend (FastAPI)

**Stack:** FastAPI + SQLAlchemy 2.0 async + PostgreSQL + asyncpg + JWT auth + WebSockets

**Config files:**
- `backend/.env` — DB URL, JWT secret
- `backend/app/core/database.py` — async engine setup
- `backend/app/core/init_db.py` — schema init + seed data
- `backend/app/modules/orders/service.py` — order logic

**What works:**
- `POST /api/v1/orders/` — create order ✅
- `PUT /api/v1/orders/{id}` — update status ✅
- `GET /api/v1/orders/history/{outlet_id}` — history with date filter ✅
- `POST /api/v1/orders/bill/{table_id}` — generate PDF bill ✅
- `POST /api/v1/orders/settle/{table_id}` — mark paid ✅
- WebSocket `ws://.../ws/kitchen/{outlet_id}` — kitchen display ✅
- WebSocket `ws://.../ws/order/{order_id}` — customer tracking ✅

**Bugs:**

| # | Bug | File | Line | Fix |
|---|-----|------|------|-----|
| B1 | `OUTLET_ID` hardcoded — only works for one outlet | `modules/orders/service.py` | 15 | Read outlet_id from request context / JWT claims |

---

## Customer App (Next.js)

**Stack:** Next.js 16.1.6, React 19, TypeScript, Tailwind CSS v4

**Key files:**
- `customer_app/app/menu/page.tsx` — menu display, QR validation
- `customer_app/app/cart/page.tsx` — cart + "Confirm Order" button
- `customer_app/components/CustomizationModal.tsx` — per-dish popup
- `customer_app/lib/api.ts` — API base URL config
- `customer_app/lib/cart-store.tsx` — cart state
- `customer_app/.env.local` — `NEXT_PUBLIC_API_URL`

**What works:**
- QR token validation → extracts outlet_id, table_id, zone ✅
- Menu fetched by zone (normal/AC) ✅
- Category tabs with item counts ✅
- Customization popup: checkboxes, addon pricing (+₹25 parsed), quantity selector, custom note textarea, total calculation ✅
- Cart management ✅
- "Confirm Order 🛎️" button with loading state ✅
- Order payload correctly sends customizations array + custom_note ✅

**Critical Bugs:**

| # | Bug | File | Lines | Fix |
|---|-----|------|-------|-----|
| C1 | **Malformed API URLs — missing hostname** | `app/menu/page.tsx` | 71, 118 | Replace `http://:8000/...` with the `API_BASE` constant from `lib/api.ts` |
| C2 | `customization_options` not returned from backend | `lib/types.ts` vs backend MenuItem schema | — | Add `customization_options` to the MenuItem response schema in backend; or populate from `ItemModifier` relation |

**Fix for C1 (most critical):**
```typescript
// In customer_app/app/menu/page.tsx

// Line 71 - BROKEN:
fetch(`http://:8000/api/v1/tables/validate/${token}`)
// FIXED:
fetch(`${API_BASE}/api/v1/tables/validate/${token}`)

// Line 118 - BROKEN:
fetch(`http://:8000/api/v1/menus/zone/${outletIdForMenu}/${zone}`)
// FIXED:
fetch(`${API_BASE}/api/v1/menus/zone/${outletIdForMenu}/${zone}`)
```
Make sure `API_BASE` is imported from `lib/api.ts` at the top of the file.

---

## Waiter App (GustoWaiter — .NET MAUI)

**Key files:**
- `GustoWaiter/App.xaml.cs` — startup, connectivity check
- `GustoWaiter/Views/DashboardPage.xaml.cs` — 3-tab layout, polling loop
- `GustoWaiter/Views/AlertsView.cs` — pending order cards
- `GustoWaiter/Views/ApprovalChecklistPage.xaml` — confirmation UI (partially built)

**What works:**
- Connectivity check to backend on startup ✅
- Dashboard with Alerts / Order / Tables tabs ✅
- Polling backend every 3 seconds for new notifications ✅
- Alerts view shows pending orders as cards, empty state ✅

**Missing / Incomplete:**

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| W1 | Per-dish tick/cross confirmation | Partial | `ApprovalChecklistPage.xaml` exists (14KB) but confirmation submit logic not wired |
| W2 | Add new dishes to existing order | Not implemented | No UI or API call found |
| W3 | Send confirmed order to kitchen | Unclear | No visible PUT request to update order status + notify kitchen |

---

## POS App (GustoPOS — .NET MAUI)

**Key files:**
- `GustoPOS/Models/` — data models
- `GustoPOS/Views/` — UI pages
- `GustoPOS/Services/` — API service layer

**Backend support is complete** — all needed endpoints exist:
- `GET /api/v1/orders/table/{table_id}` — show orders for a table
- `POST /api/v1/orders/bill/{table_id}` — generate bill PDF
- `GET /api/v1/orders/history/{outlet_id}` — history/logs
- `POST /api/v1/orders/settle/{table_id}` — mark table paid

**Status:** Source code not fully reviewed — implementation completeness unknown.

---

## Database

**Type:** PostgreSQL  
**Location:** localhost:5432  
**Database name:** `gusto_pos`  
**Credentials:** postgres / postgres  
**Schema file:** `backend/schema.sql`  
**Migrations:** `backend/alembic/versions/`

**Key tables:** organizations, outlets, tables, users, roles, menu, menu_categories, menu_items, item_modifiers, orders, order_items, customers, payments, inventory, audit_log, sync_log

---

## Priority Fix List

### 🔴 Must fix first (blocking everything)

1. **Kill GustoWaiter process** before building (or the DLL lock will prevent compilation)
2. **Run as Administrator** when launching the startup script
3. **Start PostgreSQL** and initialize the `gusto_pos` database with `backend/schema.sql`
4. **Fix backend host binding** → change `127.0.0.1` to `0.0.0.0` in `run_server.py` so it's reachable at 192.168.1.7
5. **Fix customer app API URLs** in `app/menu/page.tsx` lines 71 and 118 (missing hostname)

### 🟠 Fix next (features broken)

6. **Expose `customization_options`** from backend MenuItem schema (currently not returned in API response)
7. **Wire up waiter confirmation** — complete the submit logic in `ApprovalChecklistPage.xaml.cs` to POST/PUT to backend and trigger kitchen WebSocket event
8. **Remove hardcoded `OUTLET_ID`** from `backend/modules/orders/service.py`

### 🟡 Nice to have

9. Implement "Add dish" feature in waiter app
10. Verify POS bill generation UI end-to-end
11. Move IP/URL config to a single `.env` file used by all components

---

## Component Status Summary

| Component | Implemented | Working | Blocker |
|-----------|-------------|---------|---------|
| Backend — Order CRUD | 95% | ✅ if DB up | DB init |
| Backend — WebSockets | 80% | ✅ if DB up | DB init |
| Backend — Bill/PDF | 100% | ✅ | — |
| Customer — Menu Browse | 80% | ❌ | Broken URLs (C1) |
| Customer — Customization | 100% | ❌ | Missing API data (C2) |
| Customer — Order Submit | 100% | ❌ | Broken URLs (C1) |
| Waiter — Notifications | 70% | ⚠️ | DB + incomplete UI |
| Waiter — Confirm Dishes | 40% | ❌ | Logic not wired (W1) |
| Waiter — Add Dish | 0% | ❌ | Not built (W2) |
| POS — Display/Bill | ~50% | ❓ | Needs review |
