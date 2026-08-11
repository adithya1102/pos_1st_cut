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

## 2026-08-11 — Correction: commit 9114c93e's message names the wrong endpoint

### The error

Commit `9114c93e` ("feat: train transport mode, outlet locality, admin username
lookup") contains one factually wrong line in its message body, under
"Outlet location Phase 1 (section 4)":

> `- locality surfaced through the admin and customer APIs. /customer/menu now`
> `  returns "Koramangala, Bengaluru" as the outlet address; ...`

The endpoint that returns the composed `"{locality}, {city}"` address string is
**`/customer/outlets`**, not `/customer/menu`. The address is built in
`CarevoService.list_outlets`, which backs `GET /api/v1/customer/outlets`.
`/customer/menu` returns dishes and has no outlet-address field at all.

**Documentation only. No code, schema, or behaviour is affected** — the message
is wrong, the commit's 31-file tree is correct and unchanged.

### Note the OTHER `/customer/menu` reference in that message is CORRECT

The same commit message mentions `/customer/menu` a second time, under
"Migrations":

> `019 codifies menu_items.tags ... /customer/menu 500s without it on every`
> `fresh deploy and new Neon branch.`

That one is accurate and must not be "corrected" by anyone reading this entry.
`/customer/menu` genuinely does SELECT `mi.tags`, so a database built without
migration 019 fails on exactly that endpoint. Only the Phase-1 line is wrong.

### Why this is recorded forward instead of amended

The error was found after `9114c93e` had already been pushed to `origin/21_7`.
A message-only amend was made locally (`2a547116`, tree byte-identical —
`118c3697`), which left local and origin diverged 1↔1 and would have required a
force-push over published history to land.

That amend was **discarded** (`git reset --hard origin/21_7`) rather than
force-pushed. Rewriting a published commit to fix one word in prose is not worth
breaking history for anyone who has already fetched it. This entry is the
correction of record.

Consistent with the standing rule above: the record is append-only, and a wrong
prior entry is superseded by a new one rather than edited in place. The same
principle now extends to commit messages — a published message is part of the
record, and its corrections belong forward, not retroactively.

### Process finding from the same episode

Three commits and one push to `21_7` (`c6cfb5aa` → `27eac507` → `9114c93e`,
pushed 21:50:15 IST) were made by a **second, concurrent Claude Code session**
running with `--dangerously-skip-permissions`, while another session was mid-task
and under instruction not to push. The concurrent session also staged files into
a shared index that the other session was preparing, which surfaced as an
unexplained staged file.

Practical rule: **one agent session per repo at a time.** Two skip-permissions
sessions sharing a working tree share one index and one HEAD, and neither sees
the other's writes until after the fact — amends silently overwrite each other,
and no merge conflict is ever raised.

---

## 2026-08-11 — Timing Engine addendum Item 2: cold-start JIT fallback (shadow mode)

Builds on `bb668762`. Two files: `app/modules/prediction/service.py` and a new
`tests/test_api_cold_start_jit.py`. **No migration** — see below.

### What it does, and what it deliberately does not

Fires only when BOTH halves of a conjunction hold, a pairing that existed
nowhere in the repo before:

```
trusted_order_count(outlet) < 30   AND   hold_tolerance_seconds(order) < 300
```

When it fires it writes `order_twin.scheduled_prep_start_at` /
`latest_safe_start_at` and emits one `PREP_SCHEDULED` event.

**IT DOES NOT CHANGE WHEN ANY KITCHEN STARTS COOKING.** Nothing reads either
column or that event to control prep — verified by search across the backend and
all three clients before building, and the payload carries `shadow_mode: true`
so no later reader mistakes a logged schedule for an instruction that was
actually given. `mark_paid` is untouched and still emits its inferred
`ORDER_ACCEPTED`/`PREP_STARTED` exactly as before. The departure-window display
stays behind the existing `GRADUATION_THRESHOLD = 300` gate in
`carevo_admin/service.py`, which this change does not touch.

### The buffer is station-specific, and grounded in existing code

The master timing-engine doc (§11.3/§11.4) is **still not in this repo** —
searched again, still absent. So the buffer comes from `STATION_DEFAULTS`, this
codebase's actual pool-defaults table, rather than a number invented for the
occasion.

`STATION_DEFAULTS` is a dict of **3-tuples**, not objects — there is no
`.hold_tolerance_s` attribute. The field is the third element, called `d_hold`
in `_resolve_item`, and the new `_jit_station_buffer_s()` reads it by the same
tuple-unpack idiom (not an index literal, so it survives the tuple gaining a
field) with `STATION_DEFAULTS["other"]` as the fallback for a missing station.

```
effective_buffer_s = min(station_pool_default, this order's own hold_tol)
```

Whichever is tighter wins. **The observable band is narrow and worth knowing:**
the gate already requires `hold_tol < 300`, and every station default except
fryer (240) and griddle (300) is >= 300 — so outside fryer-bound orders with
`hold_tol` in [240, 300), the dish's own value still wins exactly as it did
under the flat constant. Per-station is more honest than one number; it is not
expected to move much data.

The **gate threshold** (`COLD_START_JIT_HOLD_TRIGGER_S = 300`) was deliberately
left flat and NOT made station-specific. It is a hard spec threshold about
cold-start uncertainty, which is a property of the outlet's missing history, not
of any station.

### Station dimension on an order-level twin

`PREP_SCHEDULED`'s payload carries `binding_station` and `station_load_s`,
stashed from `predict_kitchen` via the same `outlet_state` idiom
`_hold_tolerance_s` already used. `order_twin` stays order-level: it has one
`scheduled_prep_start_at` column, not one per station. That mismatch is the
known simultaneous-start modelling gap — μ_ready assumes every station begins at
once, with no stagger. Carrying the breakdown in the event payload is what makes
the gap measurable from logged data before anyone builds real per-station
scheduling on an order-level column.

### No migration needed — verified, not assumed

`order_twin.scheduled_prep_start_at` and `latest_safe_start_at` already exist as
`timestamptz` nullable from migration 006, confirmed against
`information_schema` on **both** `carevo_test` and prod. Prod had **0 non-null
rows** in either column — written by no code path until now. `order_events` has
**zero CHECK constraints**, so `PREP_SCHEDULED` needed no widening (unlike
`push_notifications.kind`, which did in migration 018).

This is the first `PREP_SCHEDULED` write site in the repo. It is emitted once
per order, mirroring `PROMISE_ISSUED`'s guard — `recompute_twin` runs on every
status read, and re-emitting would turn an append-only event log into a poll log.

### Tests

**110 passing** overall, 20 in the new file (zero Item-2 tests existed before).
Seven of the twenty are regression assertions that shadow mode really is
shadow: `mark_paid`'s inferred events intact, `PREP_STARTED`'s timestamp
unmoved, order status unchanged, departure window still produced,
`PROMISE_ISSUED` still once, Item 1 (train mode) intact, Item 3
(`ITEM_UNAVAILABLE` cutoff) still enforced.

**Flaky-test finding worth remembering:** one test failed roughly 1 run in 4 by
comparing Postgres's `SELECT now()` against a clamp that uses Python's
`datetime.now()`. On Windows, Python's clock has ~15ms timer granularity while
Postgres reads a finer one, so the two disagree by a few milliseconds at random
(the observed delta was ~3ms). It was a test bug, not a code bug. **Do not
compare a DB-generated timestamp against a Python-generated one in an
assertion** — pick one clock, and prefer the clock the code under test uses.

---
