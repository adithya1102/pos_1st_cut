# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Gusto POS** — A restaurant Point-of-Sale system enabling QR-code-based dine-in ordering, kitchen display, menu management, and multi-outlet support.

Four main components:
- `gusto_pos/backend/` — FastAPI REST API (Python 3.11+, async SQLAlchemy, PostgreSQL)
- `gusto_pos/customer_app/` — Next.js 16 customer ordering frontend (React 19, TypeScript, TailwindCSS 4)
- `gusto_pos/GustoPOS/` — .NET MAUI Windows Desktop application for the Cashier/Management terminal.
- `gusto_pos/GustoWaiter/` — .NET MAUI Windows Tablet application for floor staff to manage tables and approve orders.

## Commands

### Backend

```bash
cd gusto_pos/backend

# Install dependencies
pip install -r requirements.txt

# Run development server (set PYTHONPATH first on Windows)
export PYTHONPATH=$(pwd)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Docker (starts PostgreSQL + FastAPI)
docker-compose up -d db
docker-compose up -d web

# Database migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
```

API docs at `http://localhost:8000/docs` (Swagger) and `/redoc`.

### Frontend (Next.js)

```bash
cd gusto_pos/customer_app

npm run dev      # Dev server at http://localhost:3000 (Use next dev -H 0.0.0.0 for network access)
npm run build    # Production build
npm run lint     # ESLint check
```

### Environment

Backend `.env`:
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gusto_pos
SECRET_KEY=<your_secret>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

Frontend `.env.local`:
```
NEXT_PUBLIC_API_URL=http://<backend-host>:8000
```

## Architecture

### Backend Module Structure

All business logic lives in `app/modules/`. Each module follows the same pattern:

```
module_name/
├── model.py       # SQLAlchemy ORM (inherits from Base)
├── schema.py      # Pydantic v2 request/response schemas
├── service.py     # Business logic (async CRUD)
├── controller.py  # FastAPI APIRouter (mounted in app/main.py)
```

Key modules: `auth`, `menu`, `menu_items`, `orders`, `order_items`, `customers`, `outlets`, `tables`, `users`, `roles`, `payments`, `kitchen`, `organizations`.

`app/core/` contains:
- `config.py` — Pydantic Settings (reads `.env`)
- `database.py` — async SQLAlchemy engine + `get_db` dependency
- `security.py` — JWT creation/verification

### Database Schema

Hierarchy: `organizations → outlets → tables/menus/users/orders/customers`

```text
organizations
  └── outlets
      ├── tables (qr_token for QR scanning)
      ├── menus (versioned; is_latest flag)
      │   └── menu_categories → menu_items → item_modifiers
      │                           └── price_rules (maps menu_item_id to specific zones [normal, ac] with distinct prices)
      ├── orders (readable_id, kitchen_token, order_status)
      │   └── order_items
      ├── users (staff; role_id FK)
      └── customers (phone_number lookup)

payments (order_id, outlet_id, UPI transaction records)
roles (JSONB permissions column)
```

All models have `created_at` from the shared `Base`. Async migrations use `alembic/env.py` with `run_async_migrations()`.

### Request Flow

1. Customer scans QR → Hits `POST /api/v1/tables/open` to generate a unique session token.
2. Frontend loads via dynamic token URL (e.g., `/menu/YRW5AM`) and fetches menu using `GET /api/v1/menus/zone/{outlet_id}/{zone}`.
3. Cart state managed client-side in `lib/cart-store.tsx`.
4. Order placed via `POST /api/v1/orders` → stored in DB.
5. Kitchen/Waiter notified via WebSocket (`/ws/kitchen/{outlet_id}`) or polling.
6. Order status polled at `GET /api/v1/orders/{id}`.

### Frontend Structure

`app/` uses Next.js App Router:
- `menu/page.tsx` — category + item listing
- `menu/[slug]/page.tsx` — item detail + modifiers
- `cart/page.tsx` — cart review + checkout
- `order/[id]/page.tsx` — live order status

`components/` — reusable UI (MenuItemCard, ModifierModal, CustomizationModal, etc.)

### Auth

JWT-based. Staff login via `POST /api/v1/auth/login`. Protected routes use `get_current_user` dependency. Roles store permissions as JSONB (`Owner`, `Manager`, `Kitchen` predefined).

## Known Fixes (v2.0)

Five critical bugs fixed and documented in `gusto_pos_fix/README.md`:
1. `db.refresh()` replaced with explicit query after `outlet` creation (greenlet async issue).
2. Async lazy-load issue on `Menu` creation — resolved via eager loading.
3. Alembic configured for async engine in `alembic/env.py`.
4. **Duplicate Menu Bug:** The `/menus/zone/` endpoint MUST use explicit ORM eager loading (`selectinload`) restricted to `is_latest=True` to prevent duplicate categories from old menu versions mixing with `price_rules`.
5. **C# Serialization Crash:** When modifying Python API responses (especially arrays like `customization_options`), ensure they map perfectly to C# `List<string>`. C# MAUI apps require `JsonNamingPolicy.SnakeCaseLower` to read the Python backend data.

Additional context in `gusto_pos/backend/START_HERE.md` and `QUICK_REFERENCE.md`.