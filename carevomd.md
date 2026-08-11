# carevomd — Project Activity Log

Maintained by the `carevomd` agent for this working directory
(`C:\Users\Adithya\Desktop\demo2`). This file is append/update-only:
entries are never deleted, even if the task, file, or feature they
describe is later removed — later entries record that removal instead.
Every entry carries a date and timestamp (IST, Asia/Calcutta).

---

## 2026-08-11 03:10 IST — Log created; full project history captured

First write of this log. Below is the project's story so far,
reconstructed from git history and prior working notes, plus the
current in-progress (uncommitted) state at the time of writing.

### What this project is

**Gusto POS / CareVo** — a restaurant point-of-sale and customer
ordering platform, on branch `21_7`. Components:

- `gusto_pos/backend/` — FastAPI (Python), async SQLAlchemy, raw-SQL
  migrations (no Alembic in practice, despite CLAUDE.md), live Neon
  Postgres in production.
- `customer_app/` — Flutter customer app ("CareVo Skip"): browse
  outlets, order, pay, track status, loyalty/coupons.
- `owner_app/` — owner-facing Flutter app: outlet management, auth,
  push notifications.
- `admin_app/` — admin dashboard.
- `gusto_pos/GustoPOS/`, `gusto_pos/GustoWaiter/` — .NET MAUI Windows
  apps for cashier/waiter terminals.
- Backend + admin dashboard are deployed to **Render**; database is
  **Neon** (production).

### Timeline of shipped work (most recent first)

| Date | Commit | What happened |
|---|---|---|
| 2026-08-10 23:16 | `8e7705f1` | Rebuilt the API test suite to run against a disposable/throwaway database instead of touching real data; fixed a 500 error in `redeem_points`. |
| 2026-08-10 18:30 | `c48351e1` | Swapped UPI-intent payment flow in customer_app for **Cashfree** checkout. |
| 2026-08-10 17:48 | `2971e8c2` | Wired Firebase Cloud Messaging push notifications into owner_app. |
| 2026-08-10 15:08 | `19c64d76` | owner_app now distinguishes network failure vs. wrong password vs. server error at login instead of one generic message. |
| 2026-08-10 15:03 | `5c87f4b6` | Added account deletion, an order-reject flow, an "item unavailable" checklist for kitchens, and a staff push-notification schema. |
| 2026-08-10 01:02 | `22b87967` | Built the promotion engine: CareVo Campaigns + Restaurant Offers. |
| 2026-08-08 00:53 | `a5aa484e` | Owner signup now requires email; added change-password and forgot-password flows. |
| 2026-08-08 00:18 | `932412bc` | Pinned `google-auth` version so FCM push sending actually works on the deployed backend. |
| 2026-08-07 23:14 | `71068055` | Push notifications for order status, re-engagement, and "top dish" nudges — FCM-based, feature-gated. |
| 2026-08-07 03:57 | `c535f4b7` | Canonical city list with an admin-approval flow for new city requests; phone number made mandatory at owner signup. |
| 2026-08-07 03:43 | `4d39c1b5` | City picker switched to chips (up to 8 cities) with search above that threshold. |
| 2026-08-07 03:13 | `78540902` | Fixed: cart was being lost on a failed payment; area picker now derived from real outlet city data; fixed a header overlap on the location screen. |
| 2026-08-07 01:56 | `49e45c1b` | Cart persistence, outlet images, persistent login/account access, admin activity stats, and an outlet-availability check at checkout. |
| 2026-08-06 00:05 | `f63a3c1e` | Customer profile, order history, logout, and the loyalty points + coupon system. |
| 2026-08-05 23:30 | `4e1fdc45` | Set `CUSTOMER_AUTH_ENABLED=false` in `render.yaml` to match what was actually live in prod (closed a gap where customer auth had briefly been exposed). |
| earlier | `f63a3c1e` and back | Branded app icons/labels (CareVo Skip / CareVo Owner), outlet phone numbers for admin verification, email column for admin customers page, **standalone Google Sign-In**, customer analytics dashboard, **Firebase phone OTP** (with reCAPTCHA forced on Android), Places Autocomplete origin search, the **Prediction Engine** (Steps 3–6: travel events, geofencing, shadow-mode prediction service, admin dashboard, Distance Matrix travel prediction), secure Maps API key injection, outlet soft-delete for SUPER_ADMIN, package IDs renamed to `com.carevo.*`. |

### Database migrations applied to production (from prior notes)

- **Migration 008** — Google identity columns on customers; `phone_number` made nullable (code shipped as `e324808a`).
- **Migration 009** — `outlets.phone_number varchar(20) NULL`, applied 2026-08-05.
- **Migration 010** — loyalty points, coupons, `premium_until`; applied 2026-08-05; earn rate 0.005 pts/rupee (1% back); no billing wired up yet.

### Deployment state (from prior notes)

- `gusto-pos-backend` and `carevo-admin-dashboard` are live on Render, tracking branch `21_7`, against the production Neon database.
- Customer auth toggle was briefly open in the Render dashboard, found to mismatch `render.yaml`, and was closed/reconciled by `4e1fdc45` — confirmed resolved.
- Lesson on record: the Render dashboard is the source of truth over the committed blueprint; verify live settings rather than inferring them from the repo.

### Work in progress right now (uncommitted, not yet on a commit)

As of this log entry, the working tree has:

- **New migration** `gusto_pos/backend/migrations/019_menu_item_tags.sql` — codifies a `menu_items.tags` (`json`) column that already exists by hand in production but was never in a migration, so any fresh/local database was missing it and `/customer/menu` would 500. The migration is a documented no-op against prod (`IF NOT EXISTS`).
- **`gusto_pos/backend/app/modules/menu/model.py`** — added the corresponding `tags` field to the SQLAlchemy `MenuItem` model so `create_all` produces the column on a fresh DB too.
- **`gusto_pos/backend/tests/bootstrap_test_db.py`** — removed the old manual `ALTER TABLE ... ADD COLUMN tags jsonb` workaround now that the ORM model + migration 019 cover it (note: prod is `json`, not `jsonb` — intentionally not "upgraded").
- **New integration test** `customer_app/integration_test/app_flow_test.dart` (159 lines) and matching `Key(...)` widget keys added to `login_screen.dart`, `otp_screen.dart`, `outlets_screen.dart`, and `checkout_screen.dart` — stable driver targets for an end-to-end Flutter flow test (login → OTP → browse outlets → checkout).
- **New `customer_app/PRIVACY_POLICY.md`** (143 lines) — not yet linked/committed.
- **`customer_app/android/app/build.gradle.kts`** — modified, not yet reviewed in this log.
- New **`pdf/` folder** — contains `GustoPOS_CareVo_Current_State_Inventory` in `.docx`, `.md`, and `.pdf` form (a separate project-state document, not this log).
- `.claude/settings.local.json` modified (local tooling permissions, not app behavior).
- Various `gusto_pos/GustoPOS/obj/**` and `gusto_pos/GustoWaiter/obj/**` build-artifact diffs — these are .NET build output, not source changes.

None of the above is committed yet. Next natural step, if this thread continues, is likely finishing and running the new Flutter integration test, then committing the tags-migration + test-db fix together, and separately deciding what to do with `PRIVACY_POLICY.md` and the `pdf/` inventory doc.

---

<!-- Future entries: append new dated sections below this line. Do not delete or rewrite prior entries — if something above is later removed/reverted, add a new entry noting the removal instead. -->

## 2026-08-11 — Migrations 012 + 020 applied; outlet locality (§4 phase 1) built

### Migrations applied to PROD (Neon `ep-morning-meadow-ao6m0otk-pooler`)

Both were approved by the user as previously reviewed, and both were confirmed
genuinely unapplied against `information_schema` before writing.

- **012 `outlet_locality`** — `outlets.locality varchar(80)` (nullable, no
  backfill) + partial index `idx_outlets_city_locality`. Header comment updated
  from "PROPOSED — NOT APPLIED" to "APPLIED".
- **020 `train_transport_mode`** — `customer_orders.declared_arrival_at
  timestamptz` + partial index; `push_kind_valid` CHECK widened to include
  `TRAIN_START_DUE`; `outlet_config` `CREATE TABLE IF NOT EXISTS` block was a
  verified no-op on prod (table already present, 0 rows, unchanged).

Verification note worth keeping: migration 020's `outlet_config` block was
re-checked column-by-column against `information_schema` before applying,
because three sources disagreed about its shape — the migration file, the
hand-written `migrate_outlet_config.py` (`config_value VARCHAR(500)`,
`updated_at TIMESTAMPTZ`, no `created_at`, no FK), and the file's own comment.
**Prod matched the migration file exactly**; `migrate_outlet_config.py` is stale
and does NOT describe the live table. Do not trust that script.

Applying multi-statement migration files needs the asyncpg *simple-query*
protocol (`raw.driver_connection.execute(sql)`); `conn.execute(text(sql))`
fails with "cannot insert multiple commands into a prepared statement".

### §4 phase 1 — outlet locality (built, tested)

- **Locality required at owner registration.** Enforced in `RegisterIn`
  (Pydantic), not in the DB — the column stays nullable so pre-012 outlets keep
  NULL. Same pattern `phone_number` and `email` already use. Stored trimmed.
  Deliberately free text, not a reference list like `cities`: localities are too
  numerous and inconsistently named to curate.
- **Display as "{Restaurant Name} · {Locality}"** — one definition in
  `Outlet.displayName` (Dart) and inline in the admin table; the separator is
  suppressed entirely when locality is null.
- **Admin approval blocks same-city name+locality collisions** → HTTP 409.
  Compares against ACTIVE, non-deactivated outlets only, case- and
  whitespace-insensitively. Pending/rejected/deactivated duplicates do NOT
  block, and **rejection is never blocked** — the guard gates approval only.
  Placed at approval rather than signup because signup is unauthenticated
  (blocking there leaks which restaurants exist and where) and because it must
  not stop an owner re-registering after a rejection.
- **"Open in Maps" on the customer confirm screen** (`checkout_screen.dart`) —
  plain universal URL `https://www.google.com/maps/search/?api=1&query={lat},{lng}`
  via `url_launcher` (already a dependency). No API key, no Maps SDK, no
  billing. Uses coordinates rather than a name query so it cannot land on a
  different branch of the same chain. Button hidden when the outlet has no pin.
- **Full address shown plainly** on that same screen. Note: `outlets` has **no
  street-address column at all** — "{locality}, {city}" IS the full address this
  schema holds, not a truncation. Composed server-side so both apps read one
  string.
- **GPS distance-sort untouched**, with a regression test asserting it.
- `/customer/outlets` now also returns `locality`, `latitude`, `longitude`
  (floats, not Decimal — `numeric` would serialise as a quoted string and break
  the Maps URL). It returned none of these before.

### Migration 021 — written, NOT applied

`021_outlet_relocation_request.sql` adds `pending_locality`, `pending_latitude`,
`pending_longitude`, `relocation_is_pending` + a partial index, for a FUTURE
relocation-request workflow. **Schema only — no endpoint, no queue, no UI**, by
explicit instruction. Nothing in the codebase reads these columns yet, so the
migration is inert. It is applied to the local `carevo_test` DB (bootstrap runs
every migration) but was pending Checkpoint A approval for prod as of this entry.

`relocation_is_pending` is `NOT NULL DEFAULT false` rather than nullable — a
nullable boolean carries three states for a two-state question. Flagged to the
user as a deviation from the "nullable columns" instruction.

### Tests

New `tests/test_api_outlet_locality.py` — 18 tests covering the required field,
the collision guard's allow/block matrix, the discovery payload, and the
no-password-leak guard on the admin list. **Full suite: 90 passed.** Note the
per-IP `/register` rate limit (5/hour, in-process dict) must be cleared between
tests or the sixth registration 429s for unrelated reasons.

---
## 2026-08-11 — Timing Engine Item 1 (train mode), locality §4, admin username lookup

### Commit identity

Committed on branch `21_7`. Hash lineage recorded in full, because it was messy:

- `c6cfb5aa` — first attempt. **Dead.** It silently dropped
  `tests/test_api_train_mode.py`: the file had been staged and reviewed, but was
  unstaged again before the commit ran, and because `carevomd.md` was added in the
  same operation the file count stayed at 30, so the swap did not show up in the
  summary line. Caught right after by listing committed files by name instead of
  trusting the count.
- `27eac507` — the amend that put `test_api_train_mode.py` back. 31 files,
  2219 insertions, 46 deletions.
- This entry was then appended and amended into that same commit, per the standing
  rule below, which changes the hash once more. **The live hash is the one reported
  at push**; a commit cannot contain its own hash, so it is not repeated here.

`74ff6b0d` appears in the session transcript as the post-amend hash. **It never
existed** — there is no such object in this repo. It was reported in error by the
agent, stated without being read back from git. Recorded so a future reader does
not go hunting for it.

### What shipped

- **Timing Engine addendum Item 1 — train transport mode.** Customer enters an
  expected arrival time; the kitchen is pushed when it is time to start, computed
  backwards from that arrival. `declared_arrival_at` persisted on `customer_orders`,
  sent as UTC ISO-8601 (a local-time string would be read as UTC and shift the
  notification by the offset). Delivery is a check-on-read sweep
  (`_notify_kitchen_for_due_trains`) on `GET /pos/orders`, because this deploy has
  no scheduler and Render's free tier sleeps. New `KITCHEN_START_NOTIFIED` event and
  `TRAIN_START_DUE` push kind — a prompt only: it sets no status and does not start
  prep. owner_app routes a tapped push to the existing Orders tab. Per-outlet
  last-mile constant read from existing `outlet_config`, not a new column.
- **Outlet locality — §4 phase 1.** `locality` surfaced through the admin and
  customer APIs; `/customer/menu` now returns `"Koramangala, Bengaluru"` as the
  outlet address (`outlets` has no street-address column, so locality + city is the
  whole of it). Duplicate guard on `(city, location_name, locality)` enforced at
  admin approval rather than signup — signup is unauthenticated, so blocking there
  would tell an anonymous caller which restaurants exist and where.
- **Admin username lookup.** Admin outlet rows now carry `owner_username`, taken
  from the earliest active staff row, so support can recover a login for an owner
  who has forgotten BOTH username and password. Read-only; no password material
  exposed.
- **Migrations 012 / 019 / 020 / 021.** 012 and 020 were **already applied to prod
  before this commit** — committing them brings the repo in sync with the live
  schema, it does not apply anything. 019 codifies `menu_items.tags`, which prod
  already has and live code already reads: a no-op against prod, and it exists so a
  database built from this repo alone is not missing the column (`/customer/menu`
  500s without it on every fresh deploy and new Neon branch). 021 is inert schema
  for a future relocation workflow; nothing reads it yet.
- **Also:** Play Store upload signing config (keystore and `key.properties` stay
  outside the repo; debug-signing fallback when absent, which Play rejects, so it
  cannot silently ship an unsigned release), `PRIVACY_POLICY.md`, a Flutter
  integration-test flow plus the widget keys it drives, and `SESSION_HANDOFF.md`.
- **Tests: 90 passed** against `carevo_test` (adds 18 locality + 12 train-mode).

### What is explicitly NOT in this commit

- **Addendum Item 2 (cold-start JIT prep scheduling) is NOT built.** Verified by
  direct search, not inferred: `PREP_SCHEDULED` is a defined but never-emitted
  constant (its only two occurrences are the definition and a comment saying it is
  not emitted); no code path ANDs `trusted_order_count < 30` with
  `hold_tolerance_seconds < 300` — the one `trusted_order_count` check that exists
  only widens sigma; and `order_twin.scheduled_prep_start_at` /
  `latest_safe_start_at` are written by nothing. Item 2 is the next piece of work.
- **Addendum Item 3 (`ITEM_UNAVAILABLE` cutoff at READY) shipped earlier**, in
  `d936fe85`. No part of it is in this commit.

### Files deliberately excluded

`pdf/`, `.env` (untracked and gitignored — never appears in status, cannot be
staged by accident), `.claude/settings.local.json`, and the ~60 modified MAUI build
artifacts under `GustoPOS/obj/` and `GustoWaiter/obj/`.

`CareVo_Skip_Project_Handoff_Updated.md` was **deleted from the working tree** after
this commit, by explicit instruction: `SESSION_HANDOFF.md` supersedes it, and two
competing handoff docs in-repo is a liability rather than a record. It was never
tracked, so git holds no copy. Its §1–3 (business vision, MSME registration,
product inventory, the 11-step customer flow) were product context that
`SESSION_HANDOFF.md` does not clearly duplicate.

### Standing rule established (applies to every agent, every session)

**Every commit gets a corresponding `carevomd.md` entry as part of that commit —
not a follow-up, not optional.** `carevomd.md` is a pure record: append only, never
edit or reinterpret prior entries. One structural limit found while establishing
this rule: an entry cannot cite its own commit hash, because amending the entry in
changes that hash. Cite superseded hashes and prior commits; take the live hash
from the push.

---
