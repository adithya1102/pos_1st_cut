# AGENT_GUARDRAILS.md

Operating rules for any AI agent (or automated workflow) working in this repo.
These are not suggestions — they are hard gates. When in doubt, STOP and ask.

---

## 1. Prod vs. dev branch — identify the DB before touching it

The database is **Neon Postgres**. Neon dev branches and prod share a database name
(`neondb`) and user, but each branch has a **different endpoint host** in the
connection string:

```
postgresql+asyncpg://<user>:<pw>@ep-XXXXXXXX-XXXX-pooler.<region>.aws.neon.tech/neondb
                                  ^^^^^^^^^^^^^^^^^^^^^^^^
                                  this ep-... host identifies the branch
```

- **Prod** currently resolves to host `ep-morning-meadow-ao6m0otk-pooler...`.
- A **dev branch** will have a *different* `ep-...` host. Same host = same branch.

**Rule:** Before running ANY migration or DB-touching test, read the active
`DATABASE_URL` (in `gusto_pos/backend/.env`) and confirm which branch its `ep-...`
host points to. **Never assume** a URL is "dev" because it was described that way —
a pasted string that is byte-for-byte the prod host *is prod*. If the target is
prod, say so explicitly and get approval before writing.

---

## 2. Checkpoint discipline (two mandatory human approvals)

**Checkpoint A — before applying any DB migration:**
- Show the exact SQL diff (the migration file contents).
- Wait for an explicit **"approved"** before applying. No silent apply.
- Migrations are additive raw SQL under `gusto_pos/backend/migrations/`
  (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`, idempotent). This repo
  does **not** use Alembic.

**Checkpoint B — before any `git add` / `commit` / `push`:**
- Show the FULL changed-files list and test results.
- The file list MUST be verified via real `git status` / `git diff` — **never** trust
  a subagent's self-reported list.
- Wait for a second explicit **"approved"** before committing/pushing.

**Branch rule:** Work on feature branches only (e.g. `21_7`). **Never merge to `main`
or `14_july`.** Never open/merge a PR without being asked.

**Secrets:** Never stage `gusto_pos/backend/.env`, `customer_app/.env`, or
`.claude/settings.local.json`. Confirm they are excluded before committing.

---

## 3. Fixture discipline for real DBs

Any test data created against a real DB (prod OR a dev branch) MUST:
- Be **prefixed `TEST_CAREVO_`** in its name / identifying text.
- Be torn down in reverse-FK order in a `finally` block (survives mid-test failure).
- Have teardown **proven**, not claimed: capture a **per-table row count before and
  after**, and show the delta is **0** for every table, plus prove **0 rows** anywhere
  still contain `TEST_CAREVO_`.

> Demo/seed data intended to persist (see the seed script) is the exception — it is
> deliberately kept, is NOT `TEST_CAREVO_`-prefixed, and is created only with explicit
> approval. Do not confuse persistent demo data with transient test fixtures.

---

## 4. What already exists — DO NOT rebuild or duplicate

The CareVo Skip + Owner App stack is built, tested, and on branch `21_7`. Reuse it;
do not re-implement any of the following:

- **Staff auth** — `POST /api/v1/auth/login` (username/password, form-encoded) issues a
  staff JWT; `app/modules/carevo_customer/deps.py:get_current_staff` guards `/pos/*` and
  returns a `User` with `.outlet_id`. **Both** `owner_app` and the POS reuse this — there
  is no second auth path.
- **Customer OTP auth** — `/api/v1/customer/auth/request-otp` (rate-limited) +
  `verify-otp` (stub code in dev); issues a customer JWT (`typ:"customer"`).
- **pickup_code + 3-strike lockout** — `POST /api/v1/pos/orders/verify-pickup`. After 3
  wrong attempts the order sets `is_locked=true` and returns **HTTP 423**. **Lockout is
  NOT auto-recoverable in v1** — manual unlock only, a direct DB update
  (`UPDATE customer_orders SET is_locked=false, failed_attempts=0 WHERE id=...`),
  documented in `gusto_pos/backend/OWNER_APP_README.md`. This is a deliberate pilot
  decision, not a bug.
- **`outlets.is_visible`** (migration 002) — controls customer discovery; `/customer/outlets`
  filters `is_visible=true`. Toggle via `POST /api/v1/pos/outlets/{id}/visibility`.
- **`menu_items.is_available`** + **`prep_time_minutes`** (migration 001) — availability
  toggle via `PATCH /api/v1/pos/menu-items/{id}/availability`; `/customer/menu` filters
  `is_available AND is_active`.
- **Notify system** — `POST /api/v1/pos/orders/{id}/notify` with type
  `ready_now | delayed_10 | item_unavailable`. For `item_unavailable`, `item_id` is
  **mandatory and must be a valid line item of that order** (else 422/400). Broadcasts over
  the existing in-memory WS channel `/ws/order/{order_id}` (no `/api/v1` prefix);
  `customer_app` shows a read-only banner. There is **no Redis** — the WS layer is in-memory.

Backend modules already present: `carevo_customer`, `carevo_pos`, `carevo_payments`
(stub Razorpay gateway). Flutter apps: `customer_app` (neobrutalist, customer-facing),
`owner_app` (Material 3, staff tool). Migrations are `001_carevo_skip.sql`,
`002_owner_app.sql`.

---

## 5. Scope of `--dangerously-skip-permissions`

Permitted without a per-action prompt:
- New-file scaffolding and **additive** application code (new modules, new Flutter
  screens/services, new tests).

**Never** permitted under skip-permissions, always requires the checkpoints above:
- Applying **schema changes / migrations** to any real DB (Checkpoint A).
- **`git commit` / `git push`** (Checkpoint B).
- Writing **seed/demo data to a real DB** (explicit approval first).
- Any **destructive** DB op (UPDATE/DELETE/DROP on existing rows), or modifying
  existing pre-CareVo tables, waiter/KDS/billing routes, or working files.
