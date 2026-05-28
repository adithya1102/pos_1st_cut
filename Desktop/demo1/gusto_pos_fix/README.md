# Gusto POS — Bug Fix Package

## What Was Fixed

### Bug 1 — `UndefinedColumnError` on Outlet create (500 crash)
**Root cause:** `db.refresh(outlet)` auto-loaded `outlet.orders`, which queried
the `orders` table. The ORM model had a `kitchen_token` column defined but it
didn't exist in Postgres yet → `UndefinedColumnError`.

**Fix:**  
- Replaced `db.refresh()` with a clean re-query (`SELECT * FROM outlets WHERE id = ?`)
  so no relationships are touched.
- `kitchen_token` column added via migration script.
- `OutletRead` schema intentionally excludes orders/menus — they're separate endpoints.

### Bug 2 — `MissingGreenlet` on Menu create (500 crash)
**Root cause:** After `db.commit()`, Pydantic tried to serialize `menu.categories`
during response construction. SQLAlchemy attempted a lazy-load (`SELECT * FROM categories
WHERE menu_id = ?`) — but lazy loads are illegal in async context → `MissingGreenlet`.

**Fix:**  
- All relationships set to `lazy="raise"` on models — this crashes at dev time
  if you forget to eagerly load, instead of silently producing a 500 in prod.
- `menu_crud.create_menu()` re-queries with `selectinload(Menu.categories).selectinload(Category.menu_items)`
  before returning.
- `expire_on_commit=False` set on session factory.

### Bug 3 — No schema drift protection
**Fix:** Alembic configured with async engine. `env.py` imports all models so
autogenerate can diff Python vs Postgres automatically.

---

## Apply the Fixes (Step by Step)

### Step 1 — Add missing `kitchen_token` column
```bash
cd gusto_pos/backend
python scripts/add_kitchen_token.py
```

### Step 2 — Bootstrap Alembic on existing DB
```bash
python scripts/bootstrap_migrations.py
```
This stamps the DB at `001_baseline` without running any DDL.

### Step 3 — Generate migration for kitchen_token (captures it in history)
```bash
alembic revision --autogenerate -m "add kitchen_token to orders"
alembic upgrade head
```

### Step 4 — Replace your source files
Copy these files into your project:

| This file | Replace / create at |
|-----------|---------------------|
| `app/models/base.py` | `app/models/base.py` |
| `app/models/models.py` | `app/models/models.py` |
| `app/models/__init__.py` | `app/models/__init__.py` |
| `app/core/database.py` | `app/core/database.py` |
| `app/core/config.py` | `app/core/config.py` |
| `app/modules/crud_base.py` | `app/modules/crud_base.py` |
| `app/modules/menu/schemas.py` | `app/modules/menu/schemas.py` |
| `app/modules/menu/crud.py` | `app/modules/menu/crud.py` |
| `app/modules/menu/router.py` | `app/modules/menu/router.py` |
| `app/modules/outlets/schemas.py` | `app/modules/outlets/schemas.py` |
| `app/modules/outlets/crud.py` | `app/modules/outlets/crud.py` |
| `app/modules/outlets/router.py` | `app/modules/outlets/router.py` |
| `app/main.py` | `app/main.py` |
| `alembic/env.py` | `alembic/env.py` |
| `alembic/script.py.mako` | `alembic/script.py.mako` |
| `alembic/versions/001_baseline.py` | `alembic/versions/001_baseline.py` |
| `alembic.ini` | `alembic.ini` |

### Step 5 — Verify boot
```bash
uvicorn app.main:app --reload
# → GET http://localhost:8000/health  should return {"status":"ok"}
# → POST /api/v1/outlets/            should return OutletRead (no 500)
# → POST /api/v1/menus/              should return MenuRead with categories:[] (no 500)
```

---

## Golden Rules Going Forward

| Rule | Why |
|------|-----|
| Always `selectinload()` before Pydantic serializes | `MissingGreenlet` prevention |
| Never `db.refresh(obj)` — re-query instead | Prevents implicit relationship loads |
| `lazy="raise"` on all relationships | Surfaces bugs at dev time, not prod |
| `expire_on_commit=False` on session | Safe attribute access post-commit |
| Every model change → `alembic revision --autogenerate` | Schema drift prevention |
| `OutletRead` / other reads never include large collections | Avoid graph explosion |

---

## Future: Adding WebSockets
When you layer WebSocket/real-time features on top of Menu, the same rule applies:
any data you push over the socket must be pre-loaded with `selectinload` before
entering the async serialization path. Never pass a lazy ORM object to a WebSocket
send — load it fresh with explicit options first.
