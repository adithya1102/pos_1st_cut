from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Preformatted
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "GustoProject_Documentation.pdf")

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=18*mm, rightMargin=18*mm,
    topMargin=18*mm, bottomMargin=18*mm,
)

W = A4[0] - 36*mm  # usable width

base = getSampleStyleSheet()

def style(name, **kw):
    s = ParagraphStyle(name, parent=base["Normal"], **kw)
    return s

H1 = style("H1", fontSize=20, leading=26, spaceAfter=6, spaceBefore=14,
           textColor=colors.HexColor("#1a1a2e"), fontName="Helvetica-Bold")
H2 = style("H2", fontSize=14, leading=18, spaceAfter=4, spaceBefore=12,
           textColor=colors.HexColor("#16213e"), fontName="Helvetica-Bold",
           borderPadding=(0,0,2,0))
H3 = style("H3", fontSize=11, leading=15, spaceAfter=3, spaceBefore=8,
           textColor=colors.HexColor("#0f3460"), fontName="Helvetica-Bold")
BODY = style("BODY", fontSize=9, leading=13, spaceAfter=4,
             fontName="Helvetica")
CODE = style("CODE", fontSize=7.5, leading=11, spaceAfter=4,
             fontName="Courier", backColor=colors.HexColor("#f4f4f8"),
             borderPadding=4, leftIndent=6)
BULLET = style("BULLET", fontSize=9, leading=13, leftIndent=12,
               firstLineIndent=-8, spaceAfter=2, fontName="Helvetica")
SUBTITLE = style("SUBTITLE", fontSize=11, leading=14, spaceAfter=10,
                 textColor=colors.HexColor("#444466"), fontName="Helvetica-Oblique",
                 alignment=TA_CENTER)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#ccccdd"), spaceAfter=6, spaceBefore=2)

def h1(t): return Paragraph(t, H1)
def h2(t): return Paragraph(t, H2)
def h3(t): return Paragraph(t, H3)
def body(t): return Paragraph(t, BODY)
def bullet(t): return Paragraph(f"• {t}", BULLET)
def code(t): return Preformatted(t, CODE)
def sp(n=4): return Spacer(1, n*mm)

def section_table(headers, rows, col_widths=None):
    data = [headers] + rows
    if col_widths is None:
        col_widths = [W / len(headers)] * len(headers)
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,0), 8),
        ("FONTNAME",   (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE",   (0,1), (-1,-1), 8),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#f9f9fc"), colors.white]),
        ("GRID",       (0,0), (-1,-1), 0.4, colors.HexColor("#ccccdd")),
        ("VALIGN",     (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
    ]))
    return t

story = []

# ── TITLE PAGE ──────────────────────────────────────────────────────────────
story += [
    sp(10),
    Paragraph("GUSTO POS", style("T", fontSize=32, fontName="Helvetica-Bold",
                                  textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER)),
    Paragraph("Complete Project Reference", SUBTITLE),
    Paragraph("Zero-Context Guide — Architecture, DB Design, API Layout & Data Flow",
              style("ST2", fontSize=9, alignment=TA_CENTER, textColor=colors.grey,
                    fontName="Helvetica")),
    sp(2),
    hr(),
    sp(8),
]

# ── 1. WHAT IS THIS ──────────────────────────────────────────────────────────
story += [h1("1. What Is This Project?"), hr()]
story += [
    body("Gusto POS is a <b>multi-iteration restaurant Point-of-Sale ecosystem</b>. "
         "Customers scan a QR code, browse the menu, place orders and pay. "
         "Kitchen staff see orders in real time via a Kitchen Display System (KDS). "
         "Managers get analytics and inventory. "
         "The Desktop folder contains several independent versions at different maturity levels."),
    sp(2),
]

# ── 2. TOP-LEVEL FOLDER MAP ──────────────────────────────────────────────────
story += [h1("2. Top-Level Folder Map"), hr()]
story += [code(
"""C:\\Users\\Adithya\\Desktop\\
│
├── gusto_pos/               ← PRODUCTION BUILD  (FastAPI + Next.js + SQLite)
├── pos_1st_cut/             ← ADVANCED BUILD    (FastAPI Async + PostgreSQL + Redis + WebSocket)
├── restaurant-pos-api/      ← MINIMAL API       (Express + SQLite, no frontend)
├── restaurant-sim/          ← DEMO SIMULATOR    (Express + JSON file store)
├── demo1/                   ← THIS REPO — diagnostic workspace, fix branches
│   └── gusto_pos_fix/       ← Fix iteration with Alembic migrations
│
├── Cricket_AI/              ← Experiment (Groq AI + audio)
├── socket/                  ← WebSocket experiments
├── tutorial/                ← Learning reference
│
├── App.tsx                  ← Root multi-tab POS app (Vite + React 19)
├── index.tsx                ← React entry point
├── types.ts                 ← Shared TypeScript interfaces
├── constants.tsx            ← Seed data: outlets, menu, tables, staff
├── components/              ← React UI components (POS, KDS, Tables, Payments…)
├── services/
│   ├── db.ts                ← localStorage persistence layer
│   └── geminiService.ts     ← Google Gemini AI (menu OCR + business insights)
└── package.json             ← Vite + React 19 + @google/genai"""
), sp(2)]

# ── 3. PROJECT A — gusto_pos ─────────────────────────────────────────────────
story += [h1("3. Project A — gusto_pos/  (Production Build)"), hr()]
story += [body("<b>Stack:</b> Python FastAPI · SQLite · Next.js 16 · Tailwind v4"), sp(1)]

story += [h2("3.1 Folder Structure")]
story += [code(
"""gusto_pos/
├── backend/
│   ├── main.py          ← 4 API endpoints
│   ├── models.py        ← 5 database tables (SQLModel ORM)
│   ├── database.py      ← SQLite connection + session factory
│   ├── security.py      ← JWT auth, bcrypt hashing, Haversine geofencing
│   ├── requirements.txt
│   ├── .env             ← DB URL, SECRET_KEY, token expiry
│   └── gusto_pos.db     ← SQLite file (auto-created on first run)
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx     ← Full POS dashboard: Login + 3 widgets
│   │   └── layout.tsx
│   ├── .env.local       ← NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
│   └── package.json     ← next 16, react 19, tailwind v4
│
└── launch.ps1           ← One-click: starts backend + frontend + opens browser"""
), sp(2)]

story += [h2("3.2 Database Schema (SQLite — 5 Tables)")]
story += [
    section_table(
        ["Table", "Key Columns", "Purpose"],
        [
            ["customer", "id, name, phone_number (UNIQUE)", "Customer registration"],
            ["otp_validation", "id, phone_number, otp_code, expiry_time", "OTP-based login"],
            ["outlet", "id, name, city, latitude, longitude, geofence_radius", "Restaurant branches"],
            ["menu_item", "id, name, short_code (UNIQUE), base_price, is_veg, is_active", "Searchable menu items"],
            ["order", "id, readable_id (INDEX), outlet_id (FK), table_number, status (0/1/2), total_amount, created_at", "Orders"],
        ],
        [40*mm, 90*mm, 65*mm]
    ),
    sp(2),
]

story += [h2("3.3 API Endpoints")]
story += [
    section_table(
        ["Method", "Path", "Input", "Output"],
        [
            ["POST", "/auth/login", "name, phone, otp", "JWT access_token"],
            ["GET",  "/pos/search?q=RD", "search string", "Array of menu items"],
            ["POST", "/order/validate-location", "outlet_id, u_lat, u_lon", "Geofence pass/fail + distance"],
            ["POST", "/order/create", "outlet_id, table_no, amount", "order_id, confirmation"],
        ],
        [18*mm, 62*mm, 70*mm, 45*mm]
    ),
    sp(2),
]

story += [h2("3.4 Data Flow")]
story += [code(
"""User
 │
 ├─ Login (OTP 123456) ─────────────────────► backend validates → JWT stored in browser
 │
 ├─ Search "RD" ────────────────────────────► GET /pos/search?q=RD → SQLite menu_item
 │                                                                     returns matches
 ├─ Get My Location ──────────────────────► browser geolocation API
 │   { lat, lon } ───────────────────────► POST /order/validate-location
 │                                         Haversine formula, checks within 100m of outlet
 │
 └─ Create Order ────────────────────────► POST /order/create → stored in SQLite orders"""
), sp(2)]

story += [h2("3.5 Security")]
story += [
    bullet("<b>JWT:</b> HS256, signed with SECRET_KEY, expires in 1440 min (24 h)"),
    bullet("<b>Password Hashing:</b> bcrypt with 12 rounds"),
    bullet("<b>Geofencing:</b> Haversine great-circle formula, default 100m radius per outlet"),
    bullet("<b>OTP:</b> Hardcoded '123456' for testing — replace with SMS provider in production"),
    sp(3),
]

# ── 4. PROJECT B — pos_1st_cut ───────────────────────────────────────────────
story += [h1("4. Project B — pos_1st_cut/gusto_pos/  (Advanced Build)"), hr()]
story += [body("<b>Stack:</b> Python FastAPI (async) · PostgreSQL 15 · Redis · Alembic · Next.js 15 · WebSocket · Razorpay"), sp(1)]

story += [h2("4.1 Backend Folder Structure")]
story += [code(
"""backend/app/
├── main.py                ← FastAPI: CORS, WebSocket, route registration
├── core/
│   ├── database.py        ← Async SQLAlchemy + asyncpg (PostgreSQL)
│   ├── config.py          ← Environment config (pydantic-settings)
│   ├── security.py        ← JWT + bcrypt
│   ├── auth.py            ← Authentication service
│   ├── redis.py           ← Redis cache client
│   ├── ws_manager.py      ← WebSocket connection manager (broadcast by outlet)
│   └── init_db.py         ← Schema init + seed data
├── models/
│   └── base.py            ← Base class: UUID PK + created_at timestamp
└── modules/               ← One folder per feature domain
    ├── auth/              menu/   orders/   menu_items/   order_items/
    ├── organizations/     outlets/  users/    roles/
    ├── customers/         products/  inventory/  payments/
    ├── categories/        audit_logs/  sync_logs/   ws/"""
), sp(2)]

story += [h2("4.2 Module Pattern (every feature looks like this)")]
story += [code(
"""modules/orders/
├── controller.py   ← FastAPI route handlers  (@router.post, @router.get, …)
├── service.py      ← Business logic          (create_order, settle_table, …)
├── model.py        ← SQLAlchemy ORM class    (maps to DB table)
└── schema.py       ← Pydantic shapes         (request body, response body)"""
), sp(2)]

story += [h2("4.3 Database Schema (PostgreSQL — Hierarchical)")]

story += [h3("Level 1 — Root Entities")]
story += [section_table(
    ["Table", "Key Columns", "Notes"],
    [
        ["organizations", "id UUID PK, name, gst_number, created_at", "Multi-tenant root"],
        ["roles", "id SERIAL PK, name UNIQUE, permissions JSONB", "RBAC — permissions as JSON"],
        ["customers", "id UUID PK, name, phone_number UNIQUE", "Customer profiles"],
        ["otp_validations", "id UUID PK, phone_number, otp_code, expiry_time", "OTP login sessions"],
    ],
    [38*mm, 90*mm, 67*mm]
), sp(2)]

story += [h3("Level 2 — Outlets & Staff")]
story += [section_table(
    ["Table", "Key Columns", "Notes"],
    [
        ["outlets", "id UUID PK, org_id FK, location, lat, lon, geofence_radius", "Restaurant branches"],
        ["users", "id UUID PK, username UNIQUE, hashed_password, outlet_id FK", "Staff accounts"],
        ["tables", "id UUID PK, outlet_id FK, table_number, status", "Physical tables per outlet"],
    ],
    [30*mm, 100*mm, 65*mm]
), sp(2)]

story += [h3("Level 3 — Menu")]
story += [section_table(
    ["Table", "Key Columns", "Notes"],
    [
        ["menus", "id UUID PK, name, outlet_id FK, is_active", "One menu per outlet (or zone)"],
        ["menu_categories", "id UUID PK, menu_id FK, name", "e.g. Appetizers, Main Course"],
        ["menu_items", "id UUID PK, category_id FK, name, price, image_url, is_veg, is_available", "Individual dishes"],
        ["item_modifiers", "id UUID PK, menu_item_id FK, modifier_name, extra_price", "Add-ons: extra cheese, etc."],
    ],
    [36*mm, 95*mm, 64*mm]
), sp(2)]

story += [h3("Level 4 — Orders & Payments")]
story += [section_table(
    ["Table", "Key Columns", "Notes"],
    [
        ["orders", "id UUID PK, outlet_id FK, table_id FK, customer_id FK, status, total, created_at", "Parent order record"],
        ["order_items", "id UUID PK, order_id FK, menu_item_id FK, quantity, price, modifiers JSON", "Line items"],
        ["payments", "id UUID PK, order_id FK, amount, method, razorpay_id, status", "Razorpay integration"],
    ],
    [28*mm, 105*mm, 62*mm]
), sp(2)]

story += [h3("Level 5 — Operations")]
story += [section_table(
    ["Table", "Key Columns", "Notes"],
    [
        ["inventory", "id UUID PK, outlet_id FK, product_id FK, stock_qty, reorder_level", "Stock tracking per outlet"],
        ["audit_logs", "id UUID PK, entity_type, entity_id, action, user_id, created_at", "Full activity trail"],
        ["sync_logs", "id UUID PK, device_id, last_sync_at, pending_orders", "Offline device sync state"],
    ],
    [28*mm, 105*mm, 62*mm]
), sp(2)]

story += [h2("4.4 Frontend Structure (web_app/)")]
story += [code(
"""web_app/app/
├── page.tsx            ← Landing page
├── menu/page.tsx       ← Menu browsing (QR token decoded → outlet+table)
├── cart/page.tsx       ← Cart + checkout
├── login/page.tsx      ← Staff / customer login
├── pos/page.tsx        ← Manager dashboard
├── order/page.tsx      ← Order detail
├── checkout/page.tsx   ← Payment flow (Razorpay)
├── success/page.tsx    ← Order confirmation
└── tracking/page.tsx   ← Real-time order tracking via WebSocket

web_app/
├── contexts/           ← React global state (cart, auth, outlet)
├── hooks/              ← Custom React hooks
├── lib/
│   ├── api.ts          ← Axios API client (NEXT_PUBLIC_API_URL)
│   └── cart-store.tsx  ← Cart state management
├── services/           ← Business logic helpers
└── types/              ← TypeScript interfaces"""
), sp(2)]

story += [h2("4.5 API Endpoints (pos_1st_cut)")]
story += [section_table(
    ["Method", "Path", "Purpose"],
    [
        ["POST", "/api/v1/menu/",                      "Create a menu"],
        ["GET",  "/api/v1/menu/{menu_id}",             "Get menu by ID"],
        ["GET",  "/api/v1/menu/outlet/{outlet_id}",    "All menus for an outlet"],
        ["POST", "/api/v1/menu/items/",                "Create menu item"],
        ["GET",  "/api/v1/menu/items/{item_id}",       "Get item by ID"],
        ["GET",  "/api/v1/menu/items/category/{id}",   "Items by category"],
        ["GET",  "/api/v1/orders/",                    "List all orders"],
        ["GET",  "/api/v1/orders/{order_id}",          "Order detail"],
        ["POST", "/api/v1/orders/takeaway",            "Create takeaway order"],
        ["POST", "/api/v1/orders/dinein",              "Create dine-in order"],
        ["POST", "/api/v1/orders/bill/{table_id}",     "Generate PDF bill"],
        ["POST", "/api/v1/orders/settle/{table_id}",   "Mark table as paid"],
        ["WS",   "ws://.../ws/kitchen/{outlet_id}",   "Kitchen display real-time feed"],
        ["WS",   "ws://.../ws/order/{order_id}",       "Customer order tracking feed"],
    ],
    [20*mm, 90*mm, 85*mm]
), sp(2)]

story += [h2("4.6 Complete Order Flow (End-to-End)")]
story += [code(
"""1. Customer scans QR code at table
   → Token decoded: outlet_id, table_id, zone (normal / AC)

2. Frontend: GET /api/v1/menu/outlet/{outlet_id}
   → PostgreSQL: query menus by outlet_id → return items

3. Customer browses and adds items to cart (React context, local state only)

4. Customer taps "Place Order"
   → POST /api/v1/orders/dinein { outlet_id, table_id, items[] }
   → Backend: INSERT into orders + order_items (PostgreSQL)
   → WebSocket: broadcast new order to kitchen/{outlet_id}

5. Kitchen Display System receives order via WebSocket
   → Staff marks "Preparing"
   → Backend: UPDATE orders SET status='preparing'
   → WebSocket: broadcast status to order/{order_id}

6. Customer /tracking page updates in real time (WebSocket)

7. Staff marks "Ready"
   → Customer tracking shows "Your order is ready"

8. Customer requests bill
   → POST /api/v1/orders/bill/{table_id}
   → Backend: generate PDF with reportlab, return download link

9. Customer pays via Razorpay (redirect/popup)
   → Razorpay webhook: POST /api/v1/payments
   → Backend: mark order as "paid", mark table as "available" """
), sp(2)]

# ── 5. ROOT VITE APP ──────────────────────────────────────────────────────────
story += [h1("5. Root App — App.tsx  (Offline-First Desktop POS)"), hr()]
story += [body("<b>Stack:</b> Vite · React 19 · Tailwind v4 · localStorage · Google Gemini AI"), sp(1)]

story += [h2("5.1 UI Tabs")]
story += [section_table(
    ["Tab", "Component", "Purpose"],
    [
        ["POS",        "POS.tsx",               "Place orders, assign to tables"],
        ["Menu",       "MenuManagement.tsx",    "Add/edit items + Gemini OCR from photo"],
        ["KDS",        "KDS.tsx",               "Kitchen Display System"],
        ["Tables",     "Tables.tsx",            "Table status board"],
        ["Payments",   "Payments.tsx",          "Settle bills"],
        ["Analytics",  "Analytics.tsx + AdvancedAnalytics.tsx", "Order trends and insights"],
        ["Management", "Management.tsx",        "Staff and table configuration"],
    ],
    [30*mm, 80*mm, 85*mm]
), sp(2)]

story += [h2("5.2 State Shape (persisted to localStorage)")]
story += [code(
"""AppState {
  outlets:         Outlet[]    // { id, name, location }
  currentOutletId: string      // Active outlet selection
  menu:            MenuItem[]  // { id, name, price, category, isVeg }
  orders:          Order[]     // { id, tableId, items[], total, status, timestamp }
  tables:          Table[]     // { id, name, status, capacity }
  staff:           Staff[]     // { id, name, role, phone, pin, isActive }
  isOnline:        boolean     // Network connectivity flag
  lastSynced:      number      // Epoch ms of last sync
}
Saved to localStorage["gusto_pos_state"] via services/db.ts"""
), sp(2)]

story += [h2("5.3 AI Features (Google Gemini)")]
story += [
    bullet("<b>Menu OCR:</b> Upload photo of physical menu → geminiService.ts sends base64 to gemini-3-flash-preview → returns structured JSON of items"),
    bullet("<b>Business Insights:</b> Order data passed to Gemini → LLM returns human-readable trend analysis"),
    sp(3),
]

# ── 6. OTHER PROJECTS ─────────────────────────────────────────────────────────
story += [h1("6. Other Projects"), hr()]
story += [section_table(
    ["Project", "Stack", "Purpose"],
    [
        ["restaurant-pos-api/", "Express 5 + SQLite", "Bare-bones REST API — no frontend"],
        ["restaurant-sim/",     "Express + JSON file", "Demo simulator with HTML frontend"],
        ["demo1/gusto_pos_fix/","FastAPI + Alembic",  "Fix iteration with proper DB migrations"],
        ["socket/",             "Python + React",     "WebSocket experiments"],
        ["Cricket_AI/",         "Python + Groq API",  "Unrelated: AI cricket commentary"],
    ],
    [55*mm, 55*mm, 85*mm]
), sp(2)]

# ── 7. ENVIRONMENT VARIABLES ──────────────────────────────────────────────────
story += [h1("7. Environment Variables"), hr()]

story += [h3("gusto_pos / backend .env")]
story += [code(
"""DATABASE_URL="sqlite:///./gusto_pos.db"
SECRET_KEY="75c27a7..."           # change in production
ALGORITHM="HS256"
ACCESS_TOKEN_EXPIRE_MINUTES=1440  # 24 hours"""
), sp(1)]

story += [h3("pos_1st_cut / backend .env")]
story += [code(
"""DATABASE_URL="postgresql+asyncpg://gusto_admin:gusto_password@localhost:5455/gusto_pos_v2"
SECRET_KEY="<openssl rand -hex 32>"
REDIS_URL="redis://localhost:6379/0"
ALGORITHM="HS256"
RAZORPAY_KEY_ID="..."
RAZORPAY_KEY_SECRET="..." """
), sp(1)]

story += [h3("Frontend .env.local (all Next.js projects)")]
story += [code(
"""NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
GEMINI_API_KEY="..."              # root Vite app only"""
), sp(3)]

# ── 8. HOW TO START ───────────────────────────────────────────────────────────
story += [h1("8. How to Start Each Project"), hr()]
story += [section_table(
    ["Project", "Command / Action", "URL"],
    [
        ["gusto_pos (easiest)", "Right-click launch.ps1 → Run with PowerShell", "localhost:3000 + :8000/docs"],
        ["pos_1st_cut backend", "cd backend && uvicorn app.main:app --reload", "localhost:8000"],
        ["pos_1st_cut frontend", "cd web_app && npm run dev", "localhost:3000"],
        ["Root Vite app", "npm run dev (from Desktop/)", "localhost:5173"],
        ["restaurant-pos-api", "npm run dev (from routes/)", "localhost:3000"],
    ],
    [50*mm, 95*mm, 50*mm]
), sp(2)]

story += [h2("Test Credentials (all projects)")]
story += [code(
"""Phone:     any number
OTP:       123456
Admin PIN: 1234
Chef PIN:  0000"""
), sp(3)]

# ── 9. MATURITY MAP ───────────────────────────────────────────────────────────
story += [h1("9. Project Maturity Map"), hr()]
story += [section_table(
    ["Project", "Maturity", "Status"],
    [
        ["gusto_pos/",           "██████████  100%", "Production-ready, tested, one-click launch"],
        ["pos_1st_cut/",         "████████░░   80%", "Advanced features, active development"],
        ["demo1/gusto_pos_fix/", "██████░░░░   60%", "Fix iteration, migrations in place"],
        ["restaurant-pos-api/",  "████░░░░░░   40%", "API only, no frontend"],
        ["restaurant-sim/",      "███░░░░░░░   30%", "Demo/sim only"],
        ["Root App.tsx",         "██████░░░░   60%", "Offline POS + AI, no real backend"],
        ["socket/ Cricket_AI/",  "██░░░░░░░░   20%", "Experiments only"],
    ],
    [48*mm, 52*mm, 95*mm]
), sp(2)]

# ── 10. TECHNOLOGY SUMMARY ────────────────────────────────────────────────────
story += [h1("10. Technology Stack Summary"), hr()]
story += [section_table(
    ["Layer", "gusto_pos", "pos_1st_cut", "Root App"],
    [
        ["Backend Framework", "FastAPI 0.104", "FastAPI (async)", "None"],
        ["Database",          "SQLite",        "PostgreSQL 15",   "localStorage"],
        ["ORM / DB Layer",    "SQLModel",      "SQLAlchemy 2.0 async + Alembic", "—"],
        ["Auth",              "JWT + bcrypt",  "JWT + bcrypt + RBAC", "PIN"],
        ["Real-time",         "—",             "WebSocket (ws_manager)", "—"],
        ["Cache",             "—",             "Redis",           "—"],
        ["Payments",          "—",             "Razorpay",        "—"],
        ["Frontend",          "Next.js 16",    "Next.js 15",      "Vite + React 19"],
        ["Styling",           "Tailwind v4",   "Tailwind v3.4",   "Tailwind v4"],
        ["AI / ML",           "—",             "—",               "Google Gemini"],
        ["PDF Generation",    "—",             "reportlab",       "—"],
    ],
    [42*mm, 50*mm, 65*mm, 38*mm]
), sp(2)]

doc.build(story)
print(f"PDF written: {OUTPUT}")
