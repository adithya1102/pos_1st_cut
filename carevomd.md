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

## 2026-08-12 — customer_app: dead-session handling, multi-order OTP, collected state

Builds on `06fb2de4`. Six files, all in `customer_app`. No backend change, no
migration.

### The bug that made the integration test fail

`ApiClient._send` threw on a 401 but **never cleared the stored token**.
`clearToken()` existed and was only ever called from profile logout / account
deletion. So a dead session was kept forever: every request 401'd while
`isAuthenticated` stayed `true`, and the app sat on a permanently empty screen
with no route back to login.

This is exactly what a token from ANOTHER environment does. A JWT signed with a
different `SECRET_KEY` cannot be decoded by this backend, so *every* endpoint
401s at once. It is what broke the Flutter integration test when it was pointed
at a local backend while holding a token minted by prod.

Fixed centrally in `_send`, so it covers every endpoint and every verb rather
than the one call site that surfaced it:

- clears the persisted token, bumps an `authFailures` `ValueNotifier`, throws a
  distinct `AuthExpiredException`
- `main.dart` gained a global navigator key + listener →
  `pushAndRemoveUntil(LoginScreen)`. Named route, so a burst of simultaneous
  401s (the normal case — several screens poll at once) produces ONE redirect
  instead of one per failed request.
- `AuthState` drops its cached `Customer` on the same signal, so no screen shows
  a name for a session that no longer exists.

**401 ONLY — 403 is deliberately excluded.** `get_current_customer` raises 401
for a bad token, but this API also returns 403 for ordinary authorisation
denials (`"Not your order"`, `"Simulation disabled"`) where the session is
perfectly valid. Clearing on 403 would sign a customer out for a permission
error they could not have avoided. There is a regression test pinning this
distinction; do not "simplify" it to `>= 401`.

### Multi-order OTP visibility

The single active-order banner showed only `_active.first`'s pickup code and
collapsed the rest into a count ("3 orders in progress"). Every other code was
reachable only by navigating — precisely when someone is standing at a counter
being asked for one. Replaced with **one card per in-progress order**: outlet
name, status word, and the code itself in a large accent chip, all readable
without tapping. Reuses the existing `isActive` / `activeStatuses` filtering
already built for Order History rather than inventing a second rule. Cards carry
`Key('active_order_<id>')`; an order whose payment has not settled shows
"Code soon" rather than a blank slot.

### READY vs COMPLETED — a stepper-index collision

`stepIndex` maps **both** `READY` and `COMPLETED` to 2, and the pickup screen
branched on `step >= 2`. So an order already handed over still read
"Ready to collect!" — telling a customer walking away with their food to go and
collect it. `completed` was already computed on that screen and simply unused in
the headline.

Now checked BEFORE `step >= 2`: "Enjoy your food!" with collected copy, the code
card label flips `PICKUP CODE` → `COLLECTED`, and the highlight switches off
since the code has been used. `COMPLETED` is already absent from
`activeStatuses`, so a collected order also leaves the main-screen stack on its
own — no extra filtering needed.

### Tests

`customer_app`: **29 passing** (was 16; +13 new in
`test/session_and_active_orders_test.dart`). Backend unchanged at **110**.

Two harness traps found while writing them, both worth remembering:

1. A missing `ThemeProvider` made the shared AppBar actions throw
   `ProviderNotFound`, which rendered an error widget whose *overflow* was the
   only visible symptom — it masked every real assertion in the group. If a
   widget test fails with a RenderFlex overflow in a toolbar, check for a
   missing provider before touching layout.
2. `_StatusStepper` overflows under `flutter test` because `GoogleFonts` cannot
   fetch a webfont there, so text measures differently than on a device. Given
   a wider logical surface rather than reshaping real layout around a
   font-metrics artifact.

### Disk cleanup performed alongside (not part of the commit)

Freed ~12 GB: `.gradle` (regrows on next build, expected), and the .NET
`GustoPOS/bin|obj` + `GustoWaiter/bin|obj` trees.

**Consequence worth knowing: those obj/bin trees are TRACKED in git.** Deleting
them showed up as **16,631 deletions** in `git status`. They were deliberately
NOT staged here — this commit contains only the six source files plus this entry.
The artifacts are restorable with `git checkout` or by rebuilding. Whether ~1.6 GB
of .NET build output should be tracked at all is a separate decision, left open
rather than resolved by a cleanup side effect.

Deliberately NOT deleted: `customer_app/build` (holds the signed `.aab`),
`.android/avd` (the emulator), and `Desktop/demo1` + `Desktop/meet` (outside this
repo, contents unknown — flagged rather than guessed at).

---

## 2026-08-12 — Onboarding forms brought back in line with /register

Builds on `3ea1a0d4`. Fixes a LIVE breakage: **both** onboarding forms had been
rejected with 422 on every submission.

### What was broken, and how it happened

`locality` was made REQUIRED on `RegisterIn` in `9114c93e` (the outlet-locality
work) and deployed — but neither signup UI was updated to send it. That is a
self-inflicted regression from this same session's earlier work.

Investigating it turned up a second, older gap: admin_app's onboarding form was
missing **three** required fields, not one.

| Form | Missing before this commit |
|---|---|
| `owner_app` self-signup | `locality` |
| `admin_app` admin-assisted onboarding | `locality`, `phone_number`, `email` |

Both post to the SAME `POST /api/v1/register`. Verified against the LIVE
deployed `/openapi.json`, not source:
`required: [email, locality, password, phone_number, restaurant_name, upi_id, username]`

Confirmed end-to-end against the live backend before fixing: a body without
`locality` returns 422 `{"loc":["body","locality"],"msg":"Field required"}`
(no write), and a complete body returns 201 with a correct pending outlet.
That live check used a `TEST_CAREVO_`-prefixed fixture with teardown proven —
delta 0 across organizations/outlets/users/menus/categories, 0 rows left.

### What changed

- **owner_app** — required "Area / locality" field, threaded through
  `signup_screen` -> `AuthState.register` -> `AuthService.register` -> body.
- **admin_app** — added `locality`, `phone_number`, `email`; **city is now a
  dropdown of APPROVED cities** loaded from `adminApi.cities("active")` rather
  than free text, because `/register` only accepts a city already active in the
  canonical list and a typed one is refused 422 with nothing on screen
  explaining why; latitude/longitude made required WITH range validation.

**lat/lng are required by the FORM, not by the server.** The server still
accepts an outlet with no pin, and a test pins that so nobody later assumes
otherwise. The form-level rule exists because without coordinates the customer
app cannot show the restaurant on a map or compute a distance to it.

`city` is subtler than "optional": `city` and `requested_city` are each
individually optional in the schema, but the `_exactly_one_city` validator
rejects both-or-neither, so exactly one is effectively mandatory.

### Tests

New `tests/test_api_onboarding_contract.py` (8 tests). Backend **118 passing**.

The load-bearing one enumerates required fields from `RegisterIn.model_fields`
itself rather than a hand-written list, so **the next field made required is
covered automatically** — which is precisely the failure mode that produced this
commit. Also asserts a missing field is a readable 422 naming the field and
explicitly NOT a 500, that the admin-shaped body yields the same pending outlet
plus a working owner login (verified by actually logging in), and that the
password is stored hashed.

---

## 2026-08-12 — v2 UI redesign: ticket visual language, dark theme, call button

Follows the onboarding commit. Scope is the RESOLVED portion of
`UI_REDESIGN_HANDOFF.md`; §3.1/§3.2 (restricted locations, zone hierarchy) are
deferred and NOTHING was built or scaffolded for them.

### Verified before building — some things did not need building

- **§3.7 payment method picker: NOT built.** The integration already uses
  `CFWebCheckoutPaymentBuilder` — Cashfree's *hosted* checkout, which presents
  UPI/card/netbanking/wallet inside its own page. A new picker would duplicate it.
- **Menu category chips + veg filter chips already existed** and already used
  `NeoChip`. Rebuilding them would have been churn.
- **Multi-order concurrency needs no backend change** — no single-active-order
  guard exists server-side.

### §3.6 direct call — the backend addition WAS needed

`phone_number` was absent from both `OutletOut` and `MenuOut` on live, so it was
added to `list_outlets` and `get_menu` (as `outlet_phone_number`, carried on the
menu payload so the menu screen needs no second request). Empty strings are
normalised to NULL.

**The hidden case is the COMMON case:** 5 of 7 prod outlets have no phone, and 5
of the 6 customer-visible ones. The call button is hidden entirely when null
rather than rendered dead — and that path is the one tested hardest.

### §3.3 pickup acknowledgment — acknowledgment ONLY

A plain client-side bool. Calls no endpoint, moves no status, is not persisted.
Staff verification in owner_app remains the only way an order completes. On tap
it is replaced by a note saying exactly that, so the tap cannot be misread as
"done". The test asserts on **what was NOT called** — it records every request
and fails on any POST/PATCH/DELETE after the tap.

### §3.5 OTP — system keyboard kept

The prototype's custom in-app numeric keypad was NOT built, by instruction.

### Ticket visual language + new dark theme

New `lib/theme/widgets/ticket_card.dart`: perforated top edge and dashed rules
drawn with `CustomPainter` (no image assets), plus a rotated ghost stamp.
Applied to the pickup ticket, the multi-order active stack, and order history —
so an order reads as one continuous paper object from payment to collection.

**Dark theme replaced.** The old pale-brown surfaces read as a washed-out light
theme rather than a deliberate dark mode. New palette:

```
paperCenter     #B5783A   ticket stock in dark mode
contrastDark    #0B1B2B   app background + ticket ink
contrastVibrant #00D4FF   primary / focal accent
contrastSlate   #3A77B5   secondary accent
```

`TicketColors` is theme-aware with two hand-tuned schemes, NOT one dimmed: light
is cream stock with brown ink, dark is warm tan stock printed near-black.
Dimming the cream produced a glary panel that looked like a rendering bug.

**Supersedes an earlier note in this log** which recorded the ticket palette as
deliberately theme-independent. That decision was reversed; the palette is now
theme-aware.

### A real layout bug this surfaced

Taller ticket cards plus the new search bar exposed a genuine fault: the
active-order stack renders OUTSIDE the outlet list's scroll view, so its height
comes straight out of the list's. Three concurrent orders squeezed the
restaurant list to **6 pixels** — the orders pushed away the thing you opened the
screen to do. Caught by a test. Fixed by capping the stack at ~38% of viewport
height and letting it scroll internally, NOT by relaxing the assertion.

### Could not be built honestly

The prototype's **veg and rating filter chips for the outlet LIST** were not
built: `Outlet` has no veg or rating field and neither exists server-side. The
three chips the data actually supports were built instead (Nearest first /
Offers / Open now). Rating would need a new table and a review flow — its own
decision, not a silent stub.

### Tests

`customer_app` **41 passing** (was 29): +9 in new `test/v2_redesign_test.dart`,
+3 search/filter. Backend **118**. One existing assertion updated, not a
regression: the collected ticket renders "COLLECTED" twice (header label + ghost
stamp), so `findsOneWidget` became `findsNWidgets(2)`.

**Still not restyled:** login, OTP, cart, checkout.

### Amendment — v2 is SINGLE-THEME, and the palette is pinned by tests

The light/dark toggle is gone. The pale/cream light scheme was **replaced**, not
toggled away from: `AppColors.light` and `AppColors.dark` are now both aliases of
one `AppColors.v2` scheme, both `AppTheme` entry points build it at
`Brightness.dark`, `themeMode` is pinned, and the theme-toggle button was removed
from the shared app-bar actions rather than left as a control that visibly does
nothing. `ThemeProvider` is retained — it still persists a preference a future
variant could read.

```
paperCenter     #B5783A   ticket stock ONLY — stays warm/paper-toned
contrastDark    #0B1B2B   app shell + ticket ink
contrastVibrant #00D4FF   single accent: active states, focal highlights
contrastSlate   #3A77B5   secondary, large/UI only
```

**Measured contrast decided where each colour is allowed:**

| pair | ratio | rule |
|---|---|---|
| `#00D4FF` on `#0B1B2B` | 9.84:1 | accent is text-safe on the shell |
| `#0B1B2B` on `#B5783A` | 4.74:1 | ticket ink passes for body text |
| `#00D4FF` on `#B5783A` | **2.08:1** | **FAILS — accent never goes on a ticket** |
| `#3A77B5` on `#0B1B2B` | 3.72:1 | large/UI only, never body text |
| white on `#0B1B2B` | 17.41:1 | body text |
| white on `#3A77B5` | 4.68:1 | filled slate may carry a label |

The ticket keeps warm tan stock while the shell is near-black. That contrast is
the point — the ticket must read as a physical object sitting on the UI, not as
another dark panel.

New `test/palette_test.dart` (14 tests) pins all of the above, including the
FAILING pair: a future change that "brightens up the ticket" with the accent
would ship unreadable text, and now breaks a test instead. Asserted at the
SCHEME level rather than by building `ThemeData`, because `AppTheme._build` calls
`GoogleFonts`, which cannot fetch a webfont under `flutter test`.

Pre-existing and NOT introduced here: `cream on tomato` on the danger button is
3.08:1 — large-text only. Left alone, flagged.

`customer_app` **55 passing** (was 41). No existing test asserted on colour
values, so the swap broke nothing.

---

## 2026-08-12 — Dark theme REVERSED: v2 is now end-to-end LIGHT

### Why the redesign never showed up in testing

Not a bug in the implementation. The APK on the test device was
`Desktop/carevo-apks/carevo-customer-v3.apk`, built **2026-08-11 11:08** — about
28 hours before any v2 source file was written. Verified by unzipping it: its
`libapp.so` contains `PickupScreen` and `OutletsScreen` but **zero** occurrences
of `TicketCard`. The debug APK in `build/` (2026-08-12 03:40) is equally stale;
only the release APK built at 15:43 contained the work, and it was never copied
to the distribution folder. Nothing was lost and nothing was broken — the build
simply never reached the phone.

### The dark shell is gone, not toggled away from

Reviewed and rejected. `AppColors.v2` now holds the prototype's own light
values; `AppTheme.light()` and `.dark()` both build at `Brightness.light` and
`themeMode` is pinned to `ThemeMode.light`. The navy/cyan constants
(`paperCenter`, `contrastDark`, `contrastVibrant`, `contrastSlate`) were deleted
rather than left unreferenced.

```
paper   #FFF8F3   app shell (warm white, not pure white)
surface #FFFFFF   cards
brand   #53089B   wordmark + links (text-safe: 10.65:1 on the shell)
purple  #6B2FB3   primary button FILL (white on it: 7.83:1)
mint    #AAF2CA   accent FILL — never a text colour
ink     #171512   every border and hard shadow
ticket  #FAEEDA stock / #412402 ink   (12.39:1)
```

**Measured contrast decided where each colour is allowed:**

| pair | ratio | rule |
|---|---|---|
| ink on shell | 16.34:1 | body text |
| inkSoft `#4B4453` on shell | 8.87:1 | secondary text |
| brand on shell | 10.65:1 | links, wordmark |
| white on purple | 7.83:1 | primary button label |
| ink on mint | 13.31:1 | mint chips carry dark labels |
| ticket ink on stock | 12.39:1 | ticket body text |
| ticket inkSoft `#7A5426` on stock | 5.86:1 | secondary ticket lines |
| **mint on shell / on stock** | **1.23 / 1.13:1** | **FAILS — fill only, never type** |

Ticket `inkSoft` is deliberately darker than the prototype's `#8A6A2E`, which
measures 4.38:1 on the stock and would fail normal text.

### Light theme means the Android resources too

`values-night/styles.xml` still inherited `Theme.Black.NoTitleBar`, and
`drawable-v21/launch_background.xml` used `?android:colorBackground`. On a phone
with OS dark mode on, that painted a **black** launch window and a black window
background behind a light app. Both now pin `@color/carevo_paper` (#FFF8F3), and
`appBarTheme.systemOverlayStyle` states dark status-bar icons rather than
letting the OEM shell infer them.

### Frames built this pass

Login, OTP, cart, checkout — the four the previous pass left unrestyled. The
other eight frames were already built and only needed the palette to land.

Checkout now opens with "Confirm order" and ends with the order summary printed
as a **ticket**, so the object the customer approves is recognisably the one
they will hold at the counter. The struck-through total and offer line have no
prototype equivalent; they are existing behaviour, kept, and re-inked in ticket
brown because the app's purple is not a ticket colour.

### Deliberately NOT built

- **Restricted-access gate (frame 04)** — deferred by explicit decision. No
  schema scaffolded for it either.
- **In-app OTP numeric keypad (frame 02)** — rejected. The system keyboard is
  what carries SMS one-time-code autofill. The six OTP cells are a *rendering*
  of one real `TextField` (transparent, stretched under them) that keeps
  `AutofillHints.oneTimeCode`. Six separate fields would have broken autofill,
  which is the thing being protected. Pinned by tests, including one asserting
  no on-screen digit keys exist.
- **Location drill-down (frame 03)** — blocked BY the gate exclusion, not an
  oversight. Its middle level *is* the building list, and those rows carry the
  restricted badge. `location_screen.dart` remains the two-level city/area
  picker fed by `GET /customer/areas`.

### Incidental fix this surfaced

`GoogleAuthService` read `FirebaseAuth.instance` in its **constructor**, so
merely providing the service crashed any widget test without an initialized
Firebase app. Now resolved lazily at sign-in. Production path unchanged —
`main()` initializes Firebase first.

`ThemeToggleButton` deleted: it was still in the login app bar, doing nothing.

### Tests

`customer_app` **68 passing** (was 55). `palette_test.dart` rewritten for the
light palette (18 tests, including the mint-as-text failure); new
`v2_light_screens_test.dart` (10) covers the four restyled frames and pins both
exclusions. Backend **118**, unchanged and unaffected.

Theme assertions had to move from `test` to `testWidgets`: `AppTheme._build`
calls `GoogleFonts`, which throws on the webfont fetch outside a widget binding.

---

## 2026-08-12 — Batch 2 UI/UX revision list (Tasks 1-9)

Revert point tagged **`pre-batch2-redesign`** = `2604ddf5`, pushed. Recover with
`git reset --hard pre-batch2-redesign`.

### Splash is cream, and so is the window behind it

`SplashScreen` was purple; it is now `AppColors.cream` (#F6EFE2) — the app's
existing warm tone, no new hex. The white-on-purple text went to ink, which is
the actual work: `c.onPrimary` is white and would have been invisible.

A new Android colour `carevo_splash` paints the native launch window the same
value, so launch hands over to the Flutter splash with no colour step.
`carevo_paper` (#FFF8F3) still backs the app shell.

### The location prompt was in-app, so it was resizable

Answering the question the task asked first: **"Allow location" was a custom
in-app NeoCard**, roughly half the screen, purple. The native OS dialog only
appears *after* tapping it. So the panel is now a small `Near me` chip anchored
top-right beside the header. The OS dialog is untouched and untouchable.

### City selection: rows, always-search, alphabetical

`AreaPicker` was chips, with a search field that appeared only above 8 cities.
Now: one presentation at every size — a search field, then a full list of rows,
each carrying the city name and its restaurant count, **sorted alphabetically
ascending**. Sorting happens in the widget, not the endpoint: `/customer/areas`
orders by outlet count for its own reasons and other callers may depend on it.

**The premise that selection and navigation were the same action was wrong.**
They were already decoupled — `onSelect` set state, and a separate button
navigated. That is now pinned by a test rather than left as an accident.

### Page headers render on one line

New `PageHeader` widget: one line, scaled down to fit rather than wrapped.
`Pick a\nspot.` and `Where are\nyou?` carried hard line breaks; both are gone.
The Bevan-ascender fix that used to be copy-pasted per screen now lives inside
the widget.

**The "Shock Surgent" font could not be applied — it does not exist anywhere
reachable.** Not in `design/` (which holds only the two prototypes, support.js
and a thumbnail), not as any font file in the repo, not in the google_fonts
catalogue, and not referenced in any source file. No substitute was guessed.
When the file arrives it is a one-line change inside `PageHeader`.

### Train arrival: wheels, not a clock dial

`showTimePicker` replaced with `ArrivalTimePicker` — two scrolling columns and
a band label that updates live as the hour scrolls. The label is what makes a
mis-scroll obvious: 07:30 and 19:30 read identically at a glance and only one
of them says "Evening".

**ASSUMED band ranges — reasonable defaults, NOT confirmed:**

```
Morning    05:00-11:59      Evening   17:00-20:59
Afternoon  12:00-16:59      Night     21:00-04:59  (wraps midnight)
```

Pinned by test so a correction is a deliberate edit with a visible diff. Wheel
digits are `w300` — thinner, not smaller.

Arrival time is now **mandatory in train mode**: it is the only timing signal
that mode has (no GPS origin to infer from). Blocked with an inline message on
the field plus a red border, not a silently disabled Pay button — a button that
does nothing when tapped teaches people the app is broken.

### "I'm leaving" has no purple left

The button and the en-route card sat directly under the cream pickup ticket in
the app's purple, reading as another app's button pasted on. Both now use the
ticket's own stock and ink.

### owner_app: a collected order lingers 30 minutes

It used to vanish the instant staff tapped verify — `WHERE status NOT IN
('COMPLETED',...)` — leaving no window to notice a mis-tap. `/pos/orders` now
also returns COMPLETED orders whose `pickup_verified_at` is inside
`CarevoService.COMPLETED_GRACE` (30 min), and `pickup_verified_at` is exposed
on `OwnerOrderOut` so the row can label itself "Collected 12m ago".

**The cutoff is SQL, not a client timer.** A timer would reset on every
relaunch and resurrect rows that had aged out. A test rewinds the stored
timestamp and expects the row to disappear with no client involved at all —
only possible if the server owns the window. History and the admin log read
their own queries and are untouched; a third test holds that line.

### admin_app: phone_number was ALREADY there

Verified rather than rebuilt, as asked. `<Field label="Contact phone">` is
present in `onboard/page.tsx`, in state, validated, and submitted — landed in
`8f76aa1f`, which is an ancestor of `origin/21_7`, so it is in the deployed
build. Confirmed in the compiled bundle, not just the source. **No work needed.**

### admin_app: new Restaurant tab

`GET /admin/orders/by-restaurant` — orders grouped restaurant -> day -> time.
No schema change: `customer_orders` + `outlets` already carry it, and the
hierarchy is a GROUP BY over rows that exist. Same `get_current_super_admin`
gate as every other admin route, asserted by test.

**Windowed by days, not paginated.** Paging a tree can split one restaurant's
days across two pages and render a group that looks complete but is not. The UI
is a two-level accordion; `Panel` gained an optional `actions` slot for the
7/30/90-day switch, omitted everywhere else so existing pages are unchanged.

### An asyncpg trap worth remembering

`CAST(:p AS interval)` makes asyncpg expect an interval and it rejects the
string `'30 minutes'` outright — pass a `timedelta`. Cost two failing tests
before it was obvious; it bit both new queries and the test helper.

### Tests

Backend **125** (was 118): +3 grace window, +4 Restaurant tab.
customer_app **82** (was 68): +12 arrival picker, and `area_picker_test`
rewritten for the row/always-search model the chip/threshold tests no longer
described. owner_app **1** (unchanged).

---

## 2026-08-20 — Release .aab verified AD_ID-clean; Render keep-alive workflow

Infra and verification only. No schema change, no app-code change, no migration.

### The advertising-ID check had to be redone, not read off

`com.google.android.gms.permission.AD_ID` is **absent** from the release build —
but the first answer to that question was given against a merged manifest dated
**2026-08-13**, while `android/app/src/main/java/io/flutter/plugins/GeneratedPluginRegistrant.java`
had changed on **08-14**. That file is regenerated when the plugin set changes,
so the manifest predated the current dependency graph and could not settle the
question. AD_ID is exactly the permission that arrives transitively, without any
edit to the app's own manifest, so a stale artifact is not evidence.

Rebuilt clean (`flutter clean` — verified `build/` was gone before building —
then `flutter build appbundle --release`, `bundleRelease` 225.9s, exit 0) and
re-checked. Absent at **both** layers, which is the part worth keeping:

- merged manifest (`processReleaseMainManifest/AndroidManifest.xml`, sha256
  `38D2FBDF…`): no `ad_id`, `advertising`, `advertis`, or `gms.permission`.
  13 `uses-permission` entries.
- **the shipped `base/manifest/AndroidManifest.xml` extracted from inside the
  `.aab` itself** — the intermediate is only the merger's input; the protobuf in
  the bundle is what Play actually reads. Also clean.

The shipped manifest carries four permissions the merged intermediate does not
list as `<uses-permission>`: `BIND_JOB_SERVICE` and `DUMP` (declared on
components), `c2dm.permission.SEND`, and
`gms.auth.api.signin.permission.REVOCATION_NOTIFICATION` from Google Sign-In.
All expected, none advertising-related. Anyone re-running this check should
expect them rather than treat them as a finding.

**The rebuilt `.aab` is byte-identical in size to the 08-13 one (58,882,493
bytes, delta exactly 0)** — a reproducible build with no intervening source
change, not a failed clean. sha256 `C85C5E1E24A93DE82CEF03A441508CE37859D58E9D2FDE8815DDDC361EAB166F`,
built 2026-08-20 00:25:39, at
`customer_app/build/app/outputs/bundle/release/app-release.aab`. Play Console
upload is manual and was NOT performed.

Build warnings, none fatal: `flutter_google_places_sdk_android` still applies
the Kotlin Gradle Plugin (future Flutter versions will fail the build on this —
a real deadline, not noise), Java source/target 8 obsolete, 31 packages held
back by constraints.

### Keep-alive: `.github/workflows/keep-alive.yml`

Render's free plan sleeps a service after ~15 min idle. Measured the cold start
directly rather than citing a figure: **42.6s** on a `GET /` that had gone cold.
To a tester that is indistinguishable from a dead backend.

Pings `GET https://gusto-pos-backend.onrender.com/` on `*/10 * * * *`.

**Why `/` and not `/docs`**, which is the `healthCheckPath` in `render.yaml`:
`root()` in `app/main.py` takes no `Depends(get_db)`, opens no session, and
returns a static dict; `CORSMiddleware` is the only middleware in the stack, so
there is no request-logging or event-sourcing interceptor to write a row. It is
a pure read that cannot touch prod data at any frequency. `/docs` renders
Swagger UI plus openapi.json for the same wake-up.

**Two pings 5 min apart inside one run**, rather than trusting the cron. GitHub
scheduled workflows are best-effort and run late under load — late enough to
exceed a 15-minute idle timer, which would defeat the entire point. The in-job
second ping makes the effective cadence ~5 min regardless of when the run lands.
`--max-time 120` because a legitimate cold start takes ~40s and a short timeout
would report a waking service as down. `concurrency: keep-alive` stops a delayed
run stacking on the next one.

Free because the repo is public (`adithya1102/pos_1st_cut`, verified PUBLIC), so
Actions minutes are unmetered. On a private repo this would burn roughly 4,300
minutes/month against a 2,000-minute free quota — it is only free here.

**TEMPORARY, and it will not announce itself.** Delete it when the backend
leaves the free tier or the review window closes. Two failure modes to know:
GitHub disables scheduled workflows in a repo with no pushes for 60 days, and
the job hard-fails on a non-2xx so a genuinely down backend is visible instead
of being masked by a green tick.

### Screenshot assets pruned (earlier the same day)

`customer_app/assets/marketing/store_screenshots/`: `chrome2.0/`, `chromebook/`
and `tab_7/` deleted, 16 files, keeping the 6 root phone shots. SHA-256 first
established that `chrome2.0/` and `chromebook/` were byte-identical to each
other while `tab_7/` was unique.

**These were untracked AND ungitignored**, so git held no copy and the deletion
had no undo path — 11 distinct images gone permanently. A backup was placed in
the session scratchpad, which is temporary. With the tablet and Chromebook sets
gone the listing serves phone form factors only; a configured tablet or
Chromebook listing will show a missing-assets warning until new ones are
supplied.

### Repaired in passing

`carevomd.md` line 741 had `color``` ` where a bare code fence belonged — a
stray paste sitting uncommitted in the working tree, breaking the light-palette
block's rendering. Not anyone's intended edit; corrected here.

---

## 2026-08-20 — Correction: the keep-alive ping was never firing

### What the previous entry got wrong

The entry immediately above states the keep-alive workflow "pings
`GET https://gusto-pos-backend.onrender.com/` on `*/10 * * * *`". **It was not
pinging anything.** At the time that entry was committed the workflow had never
run and could not run.

`.github/workflows/keep-alive.yml` was committed to `21_7` (`2ed5a645`). **A
`schedule` trigger only fires from the repository's DEFAULT branch**, which here
is `main`. GitHub had not registered the workflow at all: `gh workflow list
--all` returned only `admin_app CI (Linux)`, and
`GET contents/.github/workflows/keep-alive.yml?ref=main` was a **404**.
`workflow_dispatch` was equally dead — that trigger also requires the file on the
default branch, so there was not even a manual fallback.

### Why this was easy to miss, and how to not miss it again

`admin-ci.yml` lives on `21_7` and works fine, which makes putting a workflow on
the working branch look proven. It works because it triggers on **`push`**, and
push events DO run from any branch. `schedule` and `workflow_dispatch` do not.
The precedent was real but did not generalise, which is the whole trap.

**Do not treat "the file is committed" as "the workflow is live."** The check
that actually settles it is `gh workflow list --all` — a workflow absent from
that list is not registered no matter what is in the tree.

### The fix

`2ed5a645` cherry-picked onto `main` as **`ab2cc25a`**, pushed
(`e6059ccf..ab2cc25a`). One file, content verified byte-identical to the `21_7`
copy. Now confirmed live:

- `gh workflow list --all` → `keep-alive (Render free tier)  active  338073584`
- the file reads on `main` (3054 bytes) instead of 404
- a `workflow_dispatch` run was accepted on `main`, which is itself proof, since
  that trigger has the same default-branch requirement that was blocking it

**`main` was genuinely dormant before this** — checked, not assumed: tip
`e6059ccf` dated **2026-07-13** (~5 weeks stale), **zero** commits present on
`main` and absent from `21_7` (it is fully contained; `21_7` is 68 ahead), no
open PRs, no branch protection, and both `render.yaml` services deploy from
`21_7`. Nothing on `main` could be disrupted.

### The file now exists on BOTH branches — only main's copy fires

`21_7`'s copy is inert and kept only so the branches do not diverge. **The
deletion note in the previous entry now means two deletions, not one.** Removing
it from `21_7` alone would leave the ping running from `main` with nothing in the
working branch to show for it.

### A repo trap worth recording: main cannot be checked out in place

Switching the primary working tree to `main` was rejected as unsafe — 635 tracked
files differ between the branches and the tree carries 16,639 uncommitted changes
(mostly the deleted MAUI artifacts). The `.aab` itself was NOT at risk;
`customer_app/.gitignore` line 33 (`/build/`) covers it, verified rather than
assumed.

A plain `git worktree add <path> main` then **failed outright** on Windows
`MAX_PATH`: dozens of `error: unable to create file ... Filename too long` on
`gusto_pos/GustoPOS/{bin,obj}/**` — the MAUI artifact paths
(`...Microsoft.Windows.ApplicationModel.Background.UniversalBGTask.dll`,
`...RecyclerView_OnChildAttachStateChangeListenerImplementor.java`) exceed 260
chars under any non-trivial worktree root. The half-built worktree had to be
force-removed and pruned.

What worked, and what to reach for next time:

```
git worktree add --no-checkout <path> main
git -C <path> sparse-checkout init --cone
git -C <path> sparse-checkout set .github
git -C <path> checkout
```

Only `.github` plus the root files materialise, so the 17,113-file checkout —
and every long path in it — never happens. The primary tree was never touched:
still on `21_7`, still 16,639 pending changes, throughout.

---

## 2026-08-20 — PROD DATA: 7 outlets renamed, menus replaced, owner logins reset

**This entry records a change to live production data, not to schema or code.**
No migration ran; no table was altered. Committed in one transaction against the
prod Neon database (`ep-morning-meadow-ao6m0otk-pooler`).

### Backup taken first, outside the repo

`C:\Users\Adithya\Desktop\carevo-backups\prod-outlets-backup-20260820-205311.json`
(33,153 bytes) — outlets 7, menus 7, categories 34, menu_items 19, users 8,
organizations 7, plus the 17 `menu_item_id`s referenced by `customer_order_items`.
Written, then re-read and re-parsed from disk before any write ran.

**Deliberately outside the repo**: the `users` rows carry `hashed_password`, and
this repo is public. Same reason `geocodes.json` and the one-off reset script live
there too rather than under `demo2/`.

### The 7 renames, with real coordinates

| was | now | locality | city | lat, lng |
|---|---|---|---|---|
| Spice Route Kitchen | Annapoorna Tiffin Room | Koramangala | Bengaluru | 12.935737, 77.624081 |
| Rudrarthi | The Brew House Café | Indiranagar | Bengaluru | 12.973291, 77.640467 |
| Walk N Style | Meenakshi Bhavan | T Nagar | Chennai | 13.037829, 80.231836 |
| Bistro | Chettinad Spice Corner | Adyar | Chennai | 13.006450, 80.257779 |
| Vj | Golden Wok | Anna Nagar | Chennai | 13.088249, 80.207340 |
| Kochi_test | Malabar Spice Kitchen | Kakkanad | Kochi | 10.016570, 76.342750 |
| kolkata.roll | Bengal Rasoi | Salt Lake | Kolkata | 22.584789, 88.423172 |

**Coordinates came from OpenStreetMap Nominatim, not from invention.** The
project's own Maps key was tried first and refused: `REQUEST_DENIED — This API is
not activated on your API project` for the Geocoding API (the key is scoped to
Places/Distance Matrix). Nominatim needs no key; queries were rate-limited to
1/sec per its usage policy and the resolved `display_name` for each is kept in
`carevo-backups\geocodes.json` so any coordinate can be traced to what was asked.

**Six of the seven had `latitude`/`longitude` NULL before this**, and all seven had
`locality` NULL. So "Open in Maps" and GPS distance-sort were dead for those six
and work now for the first time — this was not a cosmetic rename.

### Menus: soft-delete, never hard-delete

19 existing items across the 7 menus set to `is_active=false, is_available=false`;
42 new items inserted (7 × 6). Post-state verified: 42 active, 19 inactive.

**Hard-deleting would have orphaned real order history.** 17 of the 19 are
referenced by `customer_order_items` across 80 real `customer_orders`. All 17 were
re-counted as still present after the change. `customer_order_items` also carries
`name_snap`/`price_snap`, so historical orders keep the old name and price
regardless — but the FK still needs its row.

**Existing categories reused, none created or removed**, per instruction. One
consequence worth recording: Annapoorna Tiffin Room's menu has only three
categories (Beverages, Mains, Starters) where the other six have five. **Kesari
Bath therefore sits under Mains, not Desserts** — there is no Desserts category on
that menu. That is a data-shape artifact, not a classification decision, and it is
the thing to fix first if that menu ever looks wrong.

`price_rules` is empty (0 rows) repo-wide, so items follow the existing
`base_price` convention with `normal/ac/lounge_price` NULL — matching every row
that was already there. `image_url` left NULL throughout: images are coming
separately.

### Credentials: a DELIBERATE weak-ish shared password, with a hard trigger

Usernames `smith1`–`smith7` (in the table order above), with a single shared
password for all seven. **The literal is deliberately NOT written here** — this
file is committed to a public repo, and these are working credentials into a
publicly reachable backend. It was delivered to the user in-session and is
recorded nowhere in this repository. Hashed through
`app.core.security.get_password_hash` — passlib `sha256_crypt`, the same call
owner registration uses at `carevo_customer/service.py:1471`. **No new hashing
path was introduced.** All 7 outlets already had exactly one linked user, so all
7 were updated in place; none had to be created. Prior usernames (`spice_owner`,
`smith@123`, `walknstyle_owner`, `bistro`, `Vijaya`, `adithyac`, `adithyaC`) no
longer exist and no longer authenticate.

**This is a known, accepted choice — not an accident, and not a default that
slipped through.** It is scoped to seven dummy/test outlets with no real
proprietor and no real revenue. An earlier plan for a four-letter password was
rejected in favour of a longer one specifically because the backend is publicly
reachable on Render and staff login is not gated by `CUSTOMER_AUTH_ENABLED`.

**REPLACEMENT TRIGGER — event, not date:** these credentials must be replaced with
real, non-trivial, per-owner secrets **the moment the first genuine restaurant
owner account is created on this deployment.** Not "before launch", not "when we
get to it", not on any calendar. The trigger is the existence of one real owner,
because from that instant a shared known password sits in the same table as a
real proprietor's, and every one of these seven is a working credential into a
publicly reachable backend. Whoever creates that first real account owns this
cleanup.

### Verified against the live backend, not just the DB

All 7 `POST /api/v1/auth/login` against
`https://gusto-pos-backend.onrender.com` returned **HTTP 200 with a bearer token**
— a DB write alone was not treated as proof. Two negative controls confirm the
check is real rather than an endpoint that accepts anything: `smith1` + a wrong
password → **401**, and the old `spice_owner` + the new password → **401**.

`GET /api/v1/customer/outlets` returns 401 unauthenticated, as designed, so the
customer-facing view of the rename was not verified from outside; the DB state was
verified directly instead.

### Tests

Backend **125 passed**, 0 failed (unchanged). customer_app **82**, owner_app **1**
— both unchanged. Nothing here touches code, so a moved count would itself have
been the surprise.

### Not committed

Working tree only at time of writing, by instruction: this is a prod data change,
and the commit decision was deliberately left with the user. The one-off script
`reset_outlets.py` was moved OUT of the repo to `carevo-backups\` after running —
it contains the plaintext password in a literal, and this repo is public.

---

## 2026-08-20 — TRACKED BUG (NOT FIXED): naive datetimes shift by the client's timezone

**Open item. Deliberately left unfixed — do not "tidy" this in passing.** It was
found while building the owner-queue rename filter and is unrelated to it;
folding a model-layer datetime change into that work would have put a verified
fix at risk for no reason.

### What is wrong

Every `created_at`/`updated_at` in `carevo_customer/model.py` (lines 46, 49, 83,
107, 110, 142, 183) is declared `DateTime(timezone=True)` — a Postgres
`timestamptz` — with `default=datetime.utcnow`, which returns a **naive**
datetime. SQLAlchemy's asyncpg dialect localises a naive value using the
**client machine's** timezone before binding it. So the instant written depends
on where the process runs.

Measured on an IST developer box: an order created at 16:56 UTC wall-clock was
stored as **11:26 UTC** — 5h30m in the past.

### It is CLIENT-side, which is the counter-intuitive part

The obvious diagnosis is the database session timezone, and that diagnosis is
WRONG — it was tried and disproved. With `carevo_test` set to `timezone = UTC`
and `now()` returning correct UTC, `created_at` was **still** written 5h30m
early. Anyone re-investigating should not spend time on the server setting.

### Why production is currently correct

Render runs its containers in UTC, so `datetime.utcnow()` is localised as UTC
and the stored instant is right. Prod `timezone` is `GMT`, offset `00:00:00`,
confirmed by query. **Prod data is not corrupt and needs no backfill.** The bug
is latent: it produces wrong timestamps on any non-UTC machine, which today
means every local dev run and anything a contributor runs outside UTC.

### Blast radius if it ever fires in prod

`customer_orders.created_at` now drives more than display: the owner queue's
`RENAME_CUTOFF` filter, `COMPLETED_GRACE`, the train-mode due sweep, and the
admin Restaurant tab's day buckets. A 5h30m shift would silently hide fresh
orders from an owner's queue.

### The correct fix — separate task, separate review

At the **model layer**, not at the call sites and not in the database: replace
`default=datetime.utcnow` with an explicitly UTC-aware default
(`lambda: datetime.now(timezone.utc)`, or `server_default=func.now()` so the DB
stamps it). Aware values bind unambiguously and the client's timezone stops
mattering. Every one of the seven columns above should move together, with a
test that asserts a written row's `created_at` is within seconds of `now()`
while the process runs under a non-UTC `TZ`.

### What was done instead, tonight, to keep the suite honest

`CarevoService.RENAME_CUTOFF` reads `RENAME_CUTOFF_ISO`, defaulting to the real
production instant, and `conftest.py` sets it to the epoch so the suite is not
coupled to one production date. That is a test-isolation choice, **not** a
workaround for this bug — the skew is still there on any non-UTC machine and
still needs the model-layer fix.

`carevo_test`'s default timezone was set to `UTC`
(`ALTER DATABASE carevo_test SET timezone TO 'UTC'`). Kept deliberately: it does
NOT touch the skew above, but it makes the test database match prod's `GMT`,
which matters because `carevo_admin/service.py:840` buckets the Restaurant tab
with `to_char(co.created_at, 'YYYY-MM-DD')` — and `to_char` on a `timestamptz`
renders in the **session** timezone. Before the change the test DB bucketed days
5h30m off from prod. The query's own comment already says "the DB's timezone
handling decides the date", so aligning test with prod is the correct posture,
not a partial fix.

---

## 2026-08-20 — Owner queue hides pre-rename orders; OTP diagnosed, NOT changed

### Owner queue filter

`list_active_orders` gained `AND created_at >= :rename_cutoff`. Effect measured
on prod data: the owner-facing queue drops from 54 rows to 2, with Annapoorna
Tiffin Room alone shedding 32 of the previous tenant's orders.

**Two premises corrected while doing it.** owner_app has **no order-history view
and no dashboard/summary view** — its only order call is `GET /pos/orders`. And
that live queue was where old-identity orders actually surfaced, because 52 of
them sit in non-terminal statuses (50 `CREATED`, 2 `PAID`) and so were never
excluded by the existing status filter. There was no history query to change.

Cosmetic only: 82 `customer_orders` and 88 `customer_order_items` untouched, and
the admin log still shows everything — it reads its own queries in
`carevo_admin/service.py` and `RENAME_CUTOFF` is referenced nowhere in them.
`tests/test_api_rename_cutoff.py` (3 tests) pins the hiding AND the
not-deleting, because a later "cleanup" that turned this into a DELETE would
satisfy the hiding assertion alone.

Cutoff `2026-08-20T15:40:32.960232+00:00`, taken from the rename transaction's
own clock — the identical `created_at` on all 42 inserted `menu_items` — not the
backup filename, which was 17 minutes earlier.

### OTP: both mechanisms were already present

Investigated, **nothing changed**. `autofillHints: [AutofillHints.oneTimeCode]`
is present (`otp_screen.dart:256`), inside an `AutofillGroup`, on a real
`TextField`, auto-submitting at six digits. Firebase auto-retrieval is enabled —
`verificationCompleted` stores `_autoCredential` and `verifyOtp` prefers it.

The actual cause of "feels slow" is neither: `AppConfig.forceRecaptchaFlow`
defaults `true`, forcing the reCAPTCHA webview instead of Play Integrity. Added
in `e5a1dacf` (2026-08-03) because the app was sideloaded and Play Integrity
returned `17028`. Its own comment names the exit condition — "flip this off once
the app ships on a Play track" — and that condition is now met.

**Not flipped.** Play Integrity was still failing as recently as this evening
(`INVALID_CERT_HASH 400`, `17093`), the fingerprint reached Firebase only hours
ago, and the Play-signed path has never once been observed working. Stability
must be demonstrated across several attempts before a flag governing every
tester's sign-in changes.

### Internal-testing artifact (versionCode 4)

Built with `--dart-define=FORCE_RECAPTCHA_FLOW=false`. **The committed default in
`app_config.dart` is deliberately still `true`** (`git diff` on that file is
empty) — only this one artifact carries the flag off, so no other build changes
behaviour.

```
app-release.aab   58,878,598 bytes   2026-08-20 22:41:53
sha256 2FFD4E92BE5E9E80DAF87C0896D487AA6BB826C2371A6906287861F165F47DAE
versionCode 4 / versionName 1.0.0
```

**A `--dart-define` cannot be verified statically** — it compiles into the AOT
Dart snapshot. The only proof the flag took effect is behavioural: on the
internal track, sign-in proceeds with no reCAPTCHA webview. Destined for the
**internal testing** track specifically, so the 25 real testers on the closed
track are untouched while this is verified.

### Tests

Backend **128** (was 125: +3 rename cutoff), customer_app **82**, owner_app **1**.

---

## 2026-08-21 — Admin city management: request wiring, direct add, rename

**This commit contains the city work only.** The owner-queue rename filter, the
OTP diagnosis and the timezone tracked-bug entries above describe changes that
are still in the working tree, uncommitted, at the time this lands.

### admin_app could not add a city at all; the capability already existed

Investigated before building, and almost nothing needed building. Migration 013
already provided `cities` (`status IN ('active','pending','rejected')`,
`requested_by_outlet_id`, **unique index on `lower(name)`**),
`RegisterIn.requested_city` with the `_exactly_one_city` validator, the pending
INSERT with `ON CONFLICT (lower(name)) DO NOTHING`, and admin approve/reject.
owner_app had driven it since day one via `_requestingNewCity`.

Both onboarding forms post to the SAME `/register`. So this was a missing UI,
not a missing capability. The tell: `RegisterOutletBody` in `admin_app/lib/api.ts`
already carried a comment about "both-or-neither of city / requested_city"
while never declaring the field.

### Two paths, deliberately different, and that is the point

- **owner_app (self-service): still gated.** `requested_city` lands `pending`
  and is invisible in `/cities` until an admin approves. Untouched by this
  commit — **no file under `owner_app/` was modified**, which is the concrete
  proof rather than an assurance.
- **admin_app: ungated.** New `POST /admin/cities` creates the city `active`
  immediately. An admin IS the approval authority, so routing their entry
  through a queue only they service is ceremony with no safety value.

**A separate SUPER_ADMIN route rather than a flag on `/register`**, because
`/register` is unauthenticated — a "create as active" parameter there would let
any anonymous caller extend the canonical list. The admin form creates the city
first, then registers against it by name, so it sends `city` and never
`requested_city`.

Reuse over duplicate: an existing name in any casing returns that row
(`created: false`) instead of inserting. A pending/rejected name an admin asks
for is promoted to active and audited.

### Rename — and the thing that makes it non-trivial

**`outlets.city` is a denormalised varchar, NOT a foreign key to `cities.id`.**
Verified against the live schema, not assumed: `outlets` has exactly ONE foreign
key and it is `organization_id`; there is no `city_id` column anywhere.

So nothing cascades. Renaming the `cities` row alone would strand every outlet
on the old spelling — a name no longer in the canonical list, making those
outlets unselectable at signup and invisible to any name-based lookup.
`PATCH /admin/cities/{id}` therefore rewrites `cities.name` **and** every
matching `outlets.city` in one transaction, and returns `outlets_updated` so the
UI can state the blast radius ("Renamed X to Y. N outlets updated.") instead of
implying it. A test asserts the outlet moved and that zero rows keep the old
name — that is what stops the UPDATE being "tidied away" later by someone who
assumes a FK exists.

**A collision is refused (409), never merged.** Pointing two cities' outlets at
one row relocates real restaurants and cannot be undone by renaming back. The
error names the other city and says to pick a distinct name. Case-only renames
(`Kochi` -> `KOCHI`) still work: the clash check excludes the row itself.

**Checked for existing split spellings before building — none.** All 7 outlets
sit on Bengaluru/Chennai/Kochi/Kolkata, each present in `cities`, and no
`lower(city)` group has more than one variant. Nothing was merged.

### Tests

New `test_api_admin_new_city.py` (4) and `test_api_admin_city_admin_ops.py` (6).
Backend **138 collected**. customer_app **82**, owner_app **1** — re-run, not
carried over, and unchanged because no file under either app was touched.

admin_app has **no test framework** (no test script, no test dir; CI is
`npm ci && npm run build`). Verified instead with `tsc --noEmit`, `eslint` and a
full `next build`, all clean. Adding a React harness is its own decision and was
not slipped in here.

### Known failing test at time of this commit

`test_api_restaurant_tab.py::test_the_window_excludes_older_orders` fails, and
is UNRELATED to this work — it fails in isolation and that query touches neither
`cities` nor `RENAME_CUTOFF`. `carevo_test` has accumulated 2,057 orders inside
30 days against the query's `LIMIT 2000`, so the test's deliberately-backdated
row falls off the truncated end. Fixed in the next commit rather than papered
over by truncating the database.

---

## 2026-08-21 — Restaurant tab: the cap now announces itself, and scopes

Fixes the failure recorded in the entry above. **The number was not raised** —
that is the same bug with a later date on it.

### What was actually wrong

`LIMIT 2000` was applied in SILENCE, before grouping. Past the cap the tree
dropped its oldest rows and still rendered as though complete — which is exactly
the failure mode the endpoint's own docstring cites as its reason for refusing
pagination ("a group that renders as complete but is not"). The cap reproduced
the defect it was written to avoid.

The test failure was the symptom: `carevo_test` crossed 2,057 orders in a
30-day window, the deliberately-backdated row was the oldest, and newest-first
ordering pushed it off the end. Prod is nowhere near 2000 yet, so this would
have surfaced first as a silently short admin tree, not as an error.

### Approach: keep the cap, report it (not pagination)

Pagination was rejected for the same reason the original author rejected it — a
tree and a page boundary fight, and page 2 can cut a restaurant's days in half.
That reasoning still holds. An unbounded query on a growing table is a real
hazard, so the cap stays and becomes honest instead:

- the query asks for `limit + 1` rows; getting more than `limit` back PROVES
  more exist. The spare row is discarded and `truncated` is set.
- the response is now an envelope — `groups`, `truncated`, `cap`,
  `returned_orders`, `window_days` — because a bare list has nowhere to say it
  is incomplete.
- the dashboard renders an amber banner naming the cap and suggesting a
  narrower window, rather than quietly showing a short tree.

### `outlet_id` scope — and why the test needed it

New optional `outlet_id` filter. This is what makes the regression test immune
to platform-wide volume: **a test asserting a specific order is present in the
UNSCOPED feed is not testing windowing at all once volume passes the cap** — it
is testing how many orders the database happens to hold. That is precisely how
the previous test rotted, and raising the cap would have re-armed it.

New tests are written against a cap the TEST chooses (`limit=1`), never the
production default, so no future volume can reach them:

- hitting the cap sets `truncated`, `returned_orders == cap`, and the tree's
  counts sum to exactly the surviving rows
- NOT hitting the cap leaves `truncated` false — the flag has to mean something,
  it cannot simply always be true
- `outlet_id` returns that outlet and no other

### Deploy-order safety

The response shape changed, and backend + dashboard deploy from the same branch
but not atomically. `ordersByRestaurant` therefore accepts BOTH shapes: a bare
array is normalised into an envelope with `truncated: false`. Either service can
land first without the tab breaking in the gap.

---

## 2026-08-21 — Owner-queue rename cutoff: the code lands

The entry "Owner queue hides pre-rename orders; OTP diagnosed, NOT changed"
above described this work while it was still only in the working tree — the
"Admin city management" entry says so explicitly. **The code is now committed.**
Nothing about the behaviour changed in between; this entry exists so the log
does not leave a described-but-absent change hanging.

Three files: the `RENAME_CUTOFF` constant plus the `AND created_at >= ...` clause
in `carevo_customer/service.py`, the `RENAME_CUTOFF_ISO` epoch default in
`tests/conftest.py`, and `tests/test_api_rename_cutoff.py`.

**Committed on its own, deliberately.** `carevo_customer/service.py` also holds
`check_otp_rate_limit` / `request_otp` / `verify_otp`, and Firebase/OTP work is
starting next. Leaving this uncommitted would have put an orders change and an
auth change in one dirty file, separable afterwards only with care. No textual
overlap existed — the cutoff sits at the class constant and the owner-queue
query, the OTP helpers are ~1,500 lines away — so this is about keeping the two
commits legible, not about avoiding a conflict.

Suite at time of commit: backend **141 passed, 0 failed**, customer_app **82**,
owner_app **1**.

### Still uncommitted after this, and why

- `customer_app/pubspec.yaml` (`1.0.0+1` -> `+4`) and `owner_app/pubspec.yaml`
  (`+1` -> `+2`) — version bumps from tonight's builds. Held back pending
  confirmation of which versionCodes actually reached Play, so the committed
  baseline records reality rather than a guess.
- `.claude/settings.local.json` — local tool permissions, not app behaviour.
- `UI_REDESIGN_HANDOFF.md`, `design/`, `pdf/`,
  `customer_app/assets/marketing/`, `play_store_icon_512.png` — untracked docs
  and assets, each its own decision.
- ~16,631 deleted MAUI `bin`/`obj` artifacts, tracked in git, from a disk
  cleanup. Long-standing; whether that output belongs in the repo at all is
  still open.

**`customer_app/android/app/google-services.json` is GITIGNORED**
(`customer_app/android/.gitignore:23`) and therefore not in any of this. The
refreshed copy carrying the `fa681f7c...` fingerprint exists on one machine
only. Correct for a public repo, but it means any other machine or CI builds
against the OLD single-fingerprint config and the Firebase fix would appear not
to work there. Worth knowing before the OTP work starts.

---

## 2026-08-21 — customer_app versionCode reconciled to what Play actually has

`customer_app/pubspec.yaml` committed at **`1.0.0+2`**.

### Why it moved DOWN from +4

The working tree had drifted to `+4` across three local builds while the
committed baseline still read `+1` — so the repo disagreed with the machine, and
neither matched Play. Confirmed with the user: **only versionCode 2 was ever
uploaded.** `+3` (built 2026-08-20 19:55) and `+4` (the internal-testing build
with `--dart-define=FORCE_RECAPTCHA_FLOW=false`, built 22:41) were produced
locally and never submitted.

Independent corroboration for `+2` rather than taking it on trust: the test
device carries `com.carevo.customer_app versionCode=2` with
`installerPackageName=com.android.vending`, i.e. genuinely Play-installed.

**The baseline records what Play has, not the high-water mark of local builds.**
A pubspec sitting at `+4` when Play has `+2` invites the next release to be
numbered from fiction — and Play rejects a re-upload at an existing versionCode
while silently accepting a gap, so the failure mode is a confusing rejection
later rather than an error now. `+3` and `+4` are free to be reused because Play
never saw them.

**Next release is `+3`.** The `.aab` currently on disk is the `+4` internal-
testing artifact (sha256 `2FFD4E92...`); it is NOT the next upload and would
have to be rebuilt at `+3` if that flag configuration is still wanted.

### Immediately after: bumped to +3 for the next release

`1.0.0+3` committed straight after the reconciliation above, so the two entries
are not in tension — the invariant going forward is **"pubspec carries the
versionCode the NEXT upload will use"**, and the `+2` step existed only to clear
the `+4`-vs-`+1` drift before choosing that number. `+3` is reusable precisely
because Play never received it.

Committed rather than left dirty: an uncommitted bump is how the `+4` drift
started, and the fix is an hour old.

### owner_app deliberately NOT reconciled here (see below for the OTP work)

`owner_app/pubspec.yaml` remains uncommitted at `1.0.0+2` (committed baseline
`+1`). It was outside this task, and owner_app is not distributed through Play
at all — the build on the test device was installed by
`com.google.android.packageinstaller`, i.e. sideloaded. Its versionCode
therefore has no Play constraint to reconcile against, and the bump is left as
an open decision rather than swept in alongside a change made for a different
reason.

---

## 2026-08-21 — Play Integrity enabled; three OTP entry fixes

### FORCE_RECAPTCHA_FLOW default flipped to false

The flag's own comment set the condition — "flip this off once the app ships on
a Play track" — and it is met: the device build is
`installerPackageName=com.android.vending`, genuinely Play-installed and
therefore vouchable by Play Integrity.

**Two causes, not one.** The original `17028` was a sideloading artefact. A
second cause surfaced later: the Play App Signing certificate's SHA-1 was not
registered in Firebase, so `/getProjectConfig` answered `INVALID_CERT_HASH 400`
and phone auth died before any SMS was sent. Registering `FA:68:1F:7C:...`
fixed that. Flipping the flag on the strength of the first cause alone would
have been wrong.

**Three successful sign-ins on the Play build before flipping**, spaced
deliberately rather than run back to back: 01:31, 01:44 and 15:20 — the last
after a 13.5-hour gap and a cold app start, so Play Integrity's token caches had
long since expired and re-fetched.

**Honest limit on that evidence: only 2 of the 3 were confirmed in logcat.** The
device dropped mid-capture on the third and the buffer was lost. The behavioural
result is near-conclusive anyway for this failure mode — `INVALID_CERT_HASH` /
`17093` prevent the SMS from being sent at all, which was the original symptom,
and an OTP was received and entered — but the log line itself was never seen and
is not claimed.

Restoring the reCAPTCHA path for a SIDELOADED build is still one flag:
`--dart-define=FORCE_RECAPTCHA_FLOW=true`.

### The three fixes

1. **OTP cells moved toward the vertical middle.** They sat just under the
   header — exactly where Android drops its incoming-SMS heads-up banner, so the
   field was covered at the moment the code arrived. `LayoutBuilder` +
   `ConstrainedBox(minHeight)` + `IntrinsicHeight` is what lets `Spacer` resolve
   inside a `SingleChildScrollView`; without it a flex child has unbounded
   height and throws. flex 3 above / 4 below lands the cells slightly above true
   centre so the Verify button survives the raised keyboard, and the scroll view
   stays so short screens scroll instead of overflowing.

2. **A rejected code clears itself and refocuses.** The SnackBar was REPLACED by
   a persistent inline error, not supplemented: once the field clears, a message
   that vanishes after four seconds leaves an empty field and no explanation of
   why. It dismisses on the next keypress so a stale rejection cannot hang over a
   fresh code. The failure this prevents is specific — the field auto-submits at
   six characters, so a half-corrected code fires another doomed attempt and
   burns another try against the per-hour OTP rate limit.

3. **Phone placeholder** `98765 43210` -> `Enter mobile number`. A realistic
   number reads as a pre-filled value at a glance.

**Error text is `ink`, not red.** The palette's only red is `AppColors.tomato` at
~3.4:1 on the shell, already recorded here as large-text-only; body-sized red
would have been an accessibility regression. Tomato is on the icon, the message
carries weight instead of colour.

### Build

`1.0.0+3`, built with NO `--dart-define` — the committed default is the real
configuration now, not a build-time override.

```
app-release.aab   58,892,562 bytes   2026-08-21 15:37:04
sha256 6F8E12667A1A61D819E043D0C33BD795AD05318B7A0DBDA8214627C14BDF6B10
versionCode 3 / versionName 1.0.0
```

**AD_ID regression check: absent**, 13 uses-permission, unchanged set. Worth
recording HOW, because a naive scan misleads: a raw byte sweep of the bundle
DOES hit `ad_id`/`advertis` in `classes.dex` and `libflutter.so`. Those are not
the permission — the shipped `base/manifest/AndroidManifest.xml` is clean, the
literal `com.google.android.gms.permission.AD_ID` is absent from every entry,
and the dex hit resolves to the string **`thread_id`**. Expect those substring
hits rather than treating them as a finding.

Tests: customer_app **87** (82 unchanged + 5 new in `otp_entry_fixes_test.dart`).
`flutter analyze` clean. Backend and owner_app untouched.

### SmsRetrieverHelper timeout — INVESTIGATED, NOT FIXED

`[SmsRetrieverHelper] Timed out waiting for SMS` fired in both logged attempts,
so autofill is not working in practice and the code is typed by hand. Recorded
as its own open item; no fix attempted, by instruction.

It is **not** a missing permission — the SMS Retriever API deliberately requires
none, and correctly there are none. It is also a DIFFERENT mechanism from
`AutofillHints.oneTimeCode`, which goes through Android Autofill and the keyboard
suggestion strip; the timeout is Firebase's Play-Services retriever specifically.

The retriever matches an 11-character app hash appended to the SMS body, derived
from package name + signing certificate, and Firebase generates that hash from
the **SHA-256** of the registered certificate. If the Play App Signing SHA-256 is
not registered, the SMS carries a hash that cannot match this build and the
retriever waits until it times out — exactly the observed behaviour.

**Unconfirmed, and `google-services.json` cannot settle it**: that file carries
only SHA-1 by schema (all three entries are 40 chars), so its silence on SHA-256
proves nothing. Check Firebase Console -> Project settings -> Your apps ->
`com.carevo.customer_app` -> SHA certificate fingerprints for a SHA-256 entry
matching the Play App Signing cert. From the signing-block extraction,
`FA:68:1F:7C:...` has SHA-256
`60:2E:02:D0:A0:1E:A1:32:DF:B8:03:4B:8C:52:F1:E7:8F:94:7D:42:B2:1A:6A:F5:AA:AD:0C:E9:D7:EE:8C:42`.

If that is the cause it is **not fixable app-side** — a console registration, no
code change — so flipping the flag will not have altered it either way.

### Untested path

**This build's sign-in has never been exercised.** All three successful attempts
ran on versionCode 2, which used the reCAPTCHA flow. This is the first artifact
that actually takes the Play Integrity path in production configuration — the
thing those attempts justified but did not themselves test. Internal track and a
real sign-in before Alpha.

---

## 2026-08-24 02:37 IST — Home/Discover split + 8 bug groups; sideload APK (UNCOMMITTED)

customer_app only. Backend and owner_app untouched. **Nothing committed** —
held at the user's instruction for a diff review before it lands.

### Task 2 first: where location is actually consumed

Ordered before any routing change, and it changed the answer. Consumers:
`location_screen.dart:63` ("Near me" button), `checkout_screen.dart:133`
("Use my location"), `pickup_screen.dart:112/:143` (departure ping; the 60s
en-route timer passes `allowPrompt:false`). `outlets_screen.dart` reads NO
location — it takes `lat`/`lng` as ctor params and forwards them.

Two facts decided Task 3. **Distance is server-computed**
(`carevo_customer/service.py:234 _haversine_km`, populated `:275`, sorted
`:305`); with no lat/lng every outlet returns `distance_km: null`. And there
are **no radius checks or restricted-building rules anywhere** —
`outlets.geofence_radius_meters` exists in the schema but no customer_app code
reads it.

So location stays DEFERRED; Home never touches `LocationService`. The binding
constraint is that the service raises at most one dialog per grant state, so
whichever caller asks first spends it — Home would spend it on a screen with
nothing to render from coordinates.

### One root cause served two bug groups

There was **no `WidgetsBindingObserver` anywhere in the app** and
`CartState.restored` was never read. Both group E (cart) and half of group F
(permissions) were the same gap: external state read once at launch, trusted
forever. Added a single observer in `CareVoApp` — `flush()` the cart on pause,
`syncFromDisk()` + `refreshPermission()` on resume. Cart writes are now a
serialized queue with the payload encoded synchronously at mutation time, so a
force-close cannot lose the last write and a queued write cannot clobber a
later one.

Group D was likewise one cause, not three: focus was never released. The IME
staying up, surviving a back-navigation, and the caret still blinking are all
the same focused node. `lib/widgets/focus_release.dart` holds both callers —
`NeoTextField.onTapOutside` and a `FocusReleasingObserver` on the navigator.
`onTapOutside` rather than a catch-all `GestureDetector` because it is
delivered outside the gesture arena and cannot swallow taps meant for buttons.

### Latent defect found and fixed en route

`MenuScreen.initState` called `bindOutletIfSafe` synchronously, which
`notifyListeners()` on `CartState` — whose provider sits above `MaterialApp`
and has already built that frame. That is "setState() called during build", and
it fired on **every menu open in debug**, pre-existing. Surfaced only because
the new tests mount MenuScreen; existing tests never did. Deferred to a
post-frame callback.

### Reported as blocked, not faked

`outlets` has **no hours columns** (checked every migration 001–021) and **no
rush/busy/temporarily-closed signal**. `is_open` is a hardcoded `True` literal
at `service.py:289`, so the OPEN pill and "Open now" chip currently assert
nothing. `Outlet.opensAt/closesAt/hoursLabel` and the display are wired up
against nullable fields and hide while null — they light up when a migration
adds the columns. No hours were invented. The rush indicator was not built.

Map + distance ADDED to the discovery list (`_DirectionsButton`); the checkout
copy was KEPT rather than moved — it does a different job there (last
wrong-branch check before money moves).

### Build

Sideload only, outside the Play versionCode lineage.
`--dart-define=FORCE_RECAPTCHA_FLOW=true` overrides the committed default for
this build ONLY; `app_config.dart` still reads `defaultValue: false` and
`pubspec.yaml` is still `1.0.0+3` — both verified by an empty `git diff`.
Play Integrity cannot vouch for a sideloaded install, so without the override
phone auth dies at `17028` and no SMS is sent.

```
app-release.apk   57,890,940 bytes   2026-08-24 02:35:05 IST
sha256 ea614131911d0017a12d6ee591963caf074df133c5e9f1cd4ab29df11c49f96c
```

Tests: customer_app **132** (87 unchanged + 45 new in
`bugfix_batch_2026_08_24_test.dart`), backend **141**, owner_app **1**. All
pass; `flutter analyze` clean. Backend suite hard-binds to local
`carevo_test` — prod was never touched.

---

## 2026-08-24 11:59 IST — Mandatory name capture + hide fake OPEN badge (UNCOMMITTED)

customer_app only. Folds into the SAME pending review as the 02:37 checkpoint
today — that batch is also still uncommitted, so this is one diff, not two.

### Task 2 — name on signup

`AuthState` gained `pendingName`/`setPendingName()`, held from the login
screen and applied via `PATCH /customer/me` right after `verifyOtp()` or
`signInWithGoogle()` succeeds — awaited before `notifyListeners()`, so Home's
first build already has it. **Only applied when the account is still
nameless** (`_applyPendingName` no-ops if `customer.name` is non-empty): a
returning customer types into the same required field every sign-in, and
without that guard it would silently rename an account on every login rather
than being a one-time collection.

The auth endpoints (`VerifyOtpIn`/`FirebaseAuthIn`/`GoogleAuthIn`) don't and
shouldn't take a name — everything they record comes from verified token
claims. `PATCH /customer/me` already existed as the one self-editable-field
route, so no backend change was needed.

`LoginScreen` gained a required "How can we call you?" field, opened above
the identifier field (friendliest question first). Both the identifier-driven
CTA and the standalone Google button are gated on it — the Google button
needed its own gate since it bypasses the identifier field entirely and would
otherwise have been a hole straight past the requirement.

### Task 3 — blocking prompt, one condition, no flag

`NameCaptureScreen`, gated inside `HomeScreen.build()` on
`AuthState.customer?.name` being empty — checked BEFORE the orders spinner,
so a slow `/customer/orders` response can't delay it. Rendered IN PLACE OF
Home (not pushed), with `PopScope(canPop: false)` and no AppBar/account
action, so there's no way out except a name. Deliberately no local
"already shown" flag: the absence of a name IS the condition, so it can't get
stuck showing or stuck hidden — it stops being true, permanently server-side,
the moment `NameCaptureScreen` saves.

`customer == null` (not yet fetched) does NOT block — fails open rather than
stalling an unrelated network hiccup into a false positive.

### Task 4 — hide the fake OPEN badge

Removed from `outlets_screen.dart`: the OPEN/CLOSED `_Pill`, the "Open now"
filter chip (`_openOnly`), the `isOpen`-gated tap block, and the "Unavailable"
trailing text — all four were downstream of the same hardcoded
`is_open: True` at `carevo_customer/service.py:289`. The tap gate went too,
deliberately beyond the literal "badge": leaving it would mean a customer
sees no CLOSED indicator yet taps and nothing happens, for a reason the UI no
longer explains. `Outlet.isOpen` stays in the model (round-trips through cart
persistence) but nothing reads it for display or logic now.

**Confirmed untouched**: `Outlet.hoursLabel`/`opensAt`/`closesAt` and the
hours line on the outlet card — separate, still-nullable fields from the
2026-08-24 02:37 batch, already hiding themselves until real data exists.
Nothing here needed to change for them.

### Tests

64 tests in `bugfix_batch_2026_08_24_test.dart` (appended to the same file as
the 02:37 batch, which had 45): empty-name rejection (identifier valid + no
name, name-only, whitespace-only, Google
button gated too), `AuthState`-level PATCH application (fresh nameless
account gets it, existing name is never overwritten, logout clears a pending
name), the blocking gate (appears once, un-dismissable via `PopScope`, a
failed save keeps it up with a visible reason, submitting clears it and a
pull-to-refresh does not resurrect it, a named account never sees it), and
the OPEN badge (no OPEN/CLOSED text anywhere, no `chip_open`, card stays
tappable with `is_open: false` fed in on purpose).

Two of my own test-harness bugs found and fixed en route, not app bugs: a
mock `PATCH /customer/me` that echoed the ORIGINAL name instead of the
submitted one (made the "once, not repeatedly" test fail for the wrong
reason); and a `MenuScreen` navigation assertion needing `pumpAndSettle()`
instead of a fixed-duration `pump()` to clear the post-frame-callback +
Future-completion chain.

customer_app **151** passing (132 + 19 net new against the prior 132 baseline
— the file grew from 45 to 64 tests, +19). Backend **141**, owner_app **1**,
both re-run and unaffected — zero backend/owner_app files touched this pass.
`flutter analyze` clean.

**Session-hygiene note**: the dormant session file from the 2026-08-21 sign-in
work (`5c63032e…`) showed a filesystem mtime bump to today during this run,
but its byte size was unchanged (4,039,024 bytes, same as the prior
checkpoint) and its content still ends mid-2026-08-21 — a metadata touch
(indexing/AV/sync), not new writes. Single-agent confirmed by content, not
just by the initial check.

---

## 2026-08-24 13:40 IST — Multi-city, sort bar, cart resume, item placeholders (UNCOMMITTED)

Third batch today. Folds into the SAME pending review as the 02:37 and 11:59
batches — none has landed.

### First backend changes of the day

The previous two batches were customer_app-only. This one needed three
additive query changes, all in `carevo_customer`:

1. **`list_outlets` takes a city LIST.** Was `lower(city) = lower(:city)`, a
   single equality match; now `lower(city) = ANY(CAST(:cities AS varchar[]))`.
   One bound parameter, no interpolation, works for one city or ten. The
   controller's `city` param became `Optional[list[str]] = Query(None)`, so
   `?city=A&city=B` is the union and a single `?city=X` still behaves exactly
   as before.
2. **`created_at` added to the outlet payload.** Real column, always existed,
   simply was not being sent. Backs the Newest sort.
3. **`get_menu` stopped filtering `is_available = true`.** `is_active` still
   filters (deletion is not sold-out). Sold-out items now arrive flagged so
   the app can render them as placeholders.

**Deploy dependency, flagged:** the app points at the deployed Render backend
(`AppConfig.baseUrl`). Until these are deployed, multi-city returns only the
LAST city, Newest has no data to sort on, and no unavailable items arrive.
None of it fails loudly — it just under-delivers — so this needs to be said
rather than discovered.

### A latent client bug found on the way

`ApiClient._uri` did `qp[k] = v.toString()`, which would have sent
`city=[Bengaluru, Chennai]` — one literal, nonexistent city — and returned
the wrong outlets silently. Now `Iterable` values become repeated params.

### Sort bar: three real, seven declared

`lib/models/outlet_sort.dart` holds the options AND their ordering rules, so
"what does this sort do" and "does this sort work" cannot drift. Nearest
(distance), Newest (`created_at`), Best Offers (`offer_count`) work. The other
seven each carry a `blockedBy` string naming the missing signal — ratings
table, order-volume aggregates, outlet-level price index, reviews table,
per-customer personalisation. None exists.

They are rendered greyed with a **"Coming soon"** caption and are inert three
independent ways: no `onTap` passed, wrapped in `IgnorePointer`, and
`_selectSort` refuses them even if called directly. Greying alone reads as
"temporarily broken"; the words are what distinguish "not built yet".

### Task 3 — verified, and it HAD been missed

`AreaPicker`'s search box is a raw `TextField` (it needs the clear-button
suffix), so it never picked up the `onTapOutside` default added to
`NeoTextField` last batch — the one input in the app still holding focus on a
tap-away. Applied the SAME shared `releaseFocus()`, not a second mechanism.
The route-transition half was already covered by `FocusReleasingObserver`.

### Zero cities selected → CTA disabled

Chosen over defaulting-to-all: with a default, ticking none and ticking every
box do the same thing, so nothing on screen explains what the boxes are for.
"Near me" already covers "just show me things".

### Blocked, and NOT faked

**Restaurant-closed state** — not built, per instruction. Still needs real
hours/open-status data; `outlets` has no hours columns and `is_open` remains
hardcoded `true`. Same reason the OPEN badge was removed last batch. The
ITEM-level placeholder that WAS built is a different thing: `is_available` is
real data the owner app already toggles.

### Order-history alignment

Reused the group-A pattern rather than inventing one: a shared `TicketValue`
slot (`minWidth: 116`, right-aligned) used by the price row AND by
`TicketRow`, which previously used different geometry. Caught mid-fix that
swapping `Spacer()` for a fixed gap left the row packing LEFT — the label
needed `Expanded`, not `Flexible`, to push the slot flush right.

### Tests

customer_app **186** (153 + 33 new in `ui_batch_2026_08_24b_test.dart`),
backend **147** (+6: multi-city union, single-city still narrows,
case-insensitivity, no-param, `created_at` present). owner_app **1**. All
pass; `flutter analyze` clean.

One pre-existing backend test was rewritten rather than deleted:
`test_menu_hides_unavailable_items` -> `..._returns_unavailable_items_flagged_not_hidden`,
plus a new `test_menu_still_hides_INACTIVE_items` pinning that `is_active` did
NOT come along for the ride.

Three customer_app tests were updated for deliberate behaviour changes
(`chip_nearest` -> `sort_nearest`; Home's active-order ticket -> compact link;
AreaPicker `onSelect`/`selected:String?` -> `onToggle`/`selected:Set<String>`
with `Semantics.checked` replacing `.selected`).

### Session-hygiene note

The other session file (`5c63032e…`) GREW today — 4,039,024 -> 4,047,179
bytes. Inspected rather than assumed: the new entries are 3 `user` records (a
`/model` command echo) and 1 auto-generated `away_summary`, with **zero
assistant turns and zero tool calls**, and no working-tree file was modified
in the preceding 30 minutes. A second terminal is open on this project but has
done no work.

---

## 2026-08-24 16:20 IST — Backend changes COMMITTED and pushed (520794cd)

First commit of the day. Backend only — the customer_app changes from all
three of today's batches remain uncommitted, held for a dedicated review.

### Committed: 520794cd on 21_7

Five files, 181 insertions / 21 deletions:

```
app/modules/carevo_customer/controller.py   (city param -> list)
app/modules/carevo_customer/schema.py       (OutletOut.created_at)
app/modules/carevo_customer/service.py      (the three query changes)
tests/test_api_orders.py                    (rewritten + new is_active test)
tests/test_api_outlet_locality.py           (5 new city-filter tests)
```

Pushed 37bbf4d0..520794cd after a fast-forward check
(`git merge-base --is-ancestor origin/21_7 HEAD`), then re-fetched and
confirmed local HEAD == origin/21_7.

### No Checkpoint A — VERIFIED, not assumed

Checked three ways before staging:

* `git status -- migrations/` empty — no migration added or modified.
* No ORM model file touched.
* Grepping ADDED lines under `app/` for DDL and writes
  (CREATE/ALTER/DROP/ADD COLUMN/INSERT/UPDATE/DELETE/TRUNCATE) returns
  nothing; the only SQL verbs the diff adds under `app/` are SELECT, FROM,
  WHERE and JOIN.

The UPDATE/INSERT hits in the raw diff are all in `tests/`, which conftest
hard-binds to the local `carevo_test` database. Pure read-query logic, so no
schema approval gate applied.

### Staging hygiene

Staged the five paths explicitly rather than `git add -A`. Verified afterwards
that `.env`, `.claude/settings.local.json` and every `customer_app/` file were
still unstaged.

### Session check

Automated: the other session file was byte-identical (4,047,179) to the
previous check, last real content entry 12:53:37 IST, and its only 2026-08-24
entries remain 3 `user` + 1 `system` with zero assistant turns. File evidence
only proves nothing was WRITTEN, so Adi was asked to eyeball the other
terminal directly before the push; he confirmed all other Claude CLI sessions
are closed.

### Deploy verification in progress

Render auto-deploys 21_7. Push acceptance is NOT deploy proof, so the live
backend is being polled on two unauthenticated signals visible in
`/openapi.json`: the `city` parameter turning into an array, and
`OutletOut.created_at` appearing. Immediately after the push both were still
OLD (`city` a plain string, no `created_at`) — recorded here because it is the
baseline that makes the flip meaningful.

---

### Deploy CONFIRMED live — 16:23:53 IST

Baseline immediately after the push was OLD; polled `/openapi.json` every 20s
and it flipped on attempt 6, ~4 minutes after the push:

```
16:22:05 OLD ... 16:23:29 OLD    16:23:53 NEW
```

Live schema now reads, straight from the running process:

```
city              anyOf[ array<string>, null ]   (was: anyOf[ string, null ])
OutletOut.created_at  anyOf[ date-time, null ]   (was: absent)
```

FastAPI generates that from the deployed function signature at import time, so
`type: array` cannot appear unless `Optional[list[str]] = Query(None)` is what
is actually running. This is the deployed code describing itself, not an
inference from the push succeeding.

**What could NOT be proven, and why.** An authenticated end-to-end multi-city
request against prod is not possible: `/customer/outlets` requires a customer
token, and `CUSTOMER_AUTH_ENABLED` is false on prod —
`POST /customer/auth/request-otp` answers `503 Customer login is disabled on
this deployment`. Getting a token would need both a prod env change and a prod
customer row, neither of which is in scope here. The union/narrowing/
case-insensitivity BEHAVIOUR is proven instead by the five new tests in
`test_api_outlet_locality.py`, which run against a real Postgres on this exact
commit. Recorded so nobody later reads "deploy confirmed" as "multi-city
exercised end-to-end on prod".

There is also no version/SHA endpoint on the service (root returns only
`{"status":"active"}`), so the schema flip is the available deploy signal.

### APK rebuilt against the live backend

```
app-release.apk   57,923,568 bytes   2026-08-24 16:24:55 IST
sha256 33f40a9c2688cd357d346d947675c3757857360df9662d9b33659a25d3998791
```

`--dart-define=FORCE_RECAPTCHA_FLOW=true` as every sideload build (Play
Integrity cannot vouch for a sideloaded install). `pubspec.yaml` still
`1.0.0+3` and `app_config.dart` still `defaultValue: false` — both confirmed by
an empty `git diff`. Replaces the 12:06 APK (`1569f7f4…`), which predated the
name-field, OPEN-badge and this batch's work.

Built in parallel with the deploy poll rather than after it: the APK's only tie
to the backend is the base-URL constant, which did not change, so the binary is
identical either way.

Backend tree is now clean. All customer_app changes from today's three batches
remain uncommitted and held for a dedicated review pass.

---

## 2026-08-25 11:41 IST — is_new_account backend fix DEPLOYED (b984bd69)

Second backend commit. Client half stays uncommitted with the other pending
batches, by instruction.

### The bug this unblocks

A name typed on the sign-in screen is applied afterwards via
`PATCH /customer/me`, guarded by "only if the stored name is empty" — which
existed to stop that field acting as a rename control for returning customers.

That guard silently broke Google SIGNUP. `verify_google_token` creates the row
with `name` already set from the Firebase `name` claim (the Google profile
name), so the app saw a non-empty name and discarded what had just been typed.
The greeting then showed the Google profile name — and because the sign-in
field is mandatory, the customer was made to type a name that was thrown away.

"Name is empty" cannot separate that from a name deliberately set in Profile;
both are just a non-empty string in the response. Hence a real signal rather
than loosening the guard.

### Committed: b984bd69 on 21_7

Three files, 39 insertions / 7 deletions:

```
app/modules/carevo_customer/controller.py  (both auth routes pass it through)
app/modules/carevo_customer/schema.py      (VerifyOtpOut.is_new_account)
app/modules/carevo_customer/service.py     (verify_*_token -> (customer, created))
```

Pushed 520794cd..b984bd69 after `git merge-base --is-ancestor`, then re-fetched
and confirmed local HEAD == origin/21_7.

### No Checkpoint A — verified literally, not assumed

* `git status -- migrations/` — empty.
* No ORM model file touched.
* Added lines under `app/` grepped for DDL, writes, `Column(` and
  `mapped_column` — nothing.
* Added lines grepped for SQL keywords — 5 hits on `from`, ALL of them prose
  inside comments and docstrings, verified by printing them. Zero actual SQL.

Computed-field-only: two return signatures became `tuple[Customer, bool]`, one
local flag, one Pydantic field with a default, two controllers passing it on.

### Deploy CONFIRMED live — 11:41:16 IST

Baseline captured BEFORE the push (`is_new_account` absent), then polled every
20s; flipped on attempt 8, ~4 minutes after the push.

```
VerifyOtpOut properties
  BEFORE: ['access_token', 'token_type', 'customer']
  AFTER : ['access_token', 'token_type', 'customer', 'is_new_account']
  ADDED : ['is_new_account']   REMOVED: none

  is_new_account: {"type":"boolean","default":false}
  required BEFORE == required AFTER == ['access_token','customer']
```

`required` is unchanged and the field carries `default: false`, so this is
purely additive — an older client that ignores it is unaffected, and one that
reads it from an older deploy gets the previous conservative behaviour rather
than starting to overwrite names.

### Still not exercised end to end

Same limit as the multi-city deploy: `/auth/google` needs a real Firebase
token and prod `CUSTOMER_AUTH_ENABLED` is false, so the flag's runtime value
cannot be observed on prod. What IS proven is the deployed contract (the
schema is generated from the running signatures) plus the client-side
behaviour, pinned by 4 tests in `bugfix_batch_2026_08_24_test.dart` — one of
which goes red if the guard is reverted, while the three that protect the
returning-customer case stay green.

Backend tests: **147**, unchanged — none of them cover `/auth/google` or
`/auth/firebase`, which require Firebase. Recorded as a fact about coverage,
not a proposal.

---

## 2026-08-25 12:22 IST — Google displayName seeding removed (6df95351)

Third backend commit. Client login redesign stays uncommitted, by instruction.

### Committed: 6df95351 on 21_7

One file, 17 insertions / 7 deletions, all inside `verify_google_token`:

```
app/modules/carevo_customer/service.py
```

Pushed b984bd69..6df95351 after `git merge-base --is-ancestor`, re-fetched,
local HEAD == origin/21_7 confirmed. Backend tree clean afterwards.

`customers.name` now has exactly ONE writer: `PATCH /customer/me`. The Firebase
`name` claim is unpacked as `_google_display_name` and discarded; the
`Customer(...)` constructor no longer takes `name=`, and the
`if name and not customer.name` backfill is deleted.

This supersedes the ARBITRATION added in b984bd69 rather than replacing it:
`is_new_account` is still used, but now only to decide whether to SHOW the name
screen, not to referee between two writers. Removing the second writer is the
smaller system.

Existing rows are untouched — this stops future writes, it does not rewrite
history. A Google account already carrying a display name keeps it until its
owner changes it in Account -> Your name.

### No Checkpoint A — verified literally

* `git status -- migrations/` — empty.
* No ORM model and no Pydantic schema file modified.
* Diff grepped in BOTH directions for DDL, `Column(`, `mapped_column` — nothing.
* Scope: the three hunks sit at lines 208-260; `verify_google_token` spans
  182-261 (next def at 262), so every hunk is inside it.
  `verify_firebase_token` (133-181) is untouched.

### Deploy NOT confirmed — and openapi cannot confirm it

Unlike the previous two deploys, there is no observable signal available:

* `/openapi.json` is byte-identical before and after (sha256 `2c5a151b…`), which
  is EXPECTED — no signature or model changed — and therefore carries zero
  information about whether the deploy landed.
* There is no version/commit/health endpoint (root returns `{"status":"active"}`).

What WOULD confirm it: a fresh Google signup, then reading `customers.name` for
that new row BEFORE the app issues `PATCH /customer/me`. Empty = live.

### CORRECTION to earlier entries in this log

Previous entries said the Google path could not be exercised on prod because
`CUSTOMER_AUTH_ENABLED=false`. **That is wrong for `/auth/google`.** Probed
directly:

```
POST /customer/auth/google  -> 401 {"detail":"Malformed Firebase token"}
POST /customer/auth/request-otp -> 503 {"detail":"Customer login is disabled..."}
```

`/auth/google` and `/auth/firebase` deliberately SKIP the
`_require_customer_auth_enabled()` gate — the controller docstrings say so —
because they verify against Google's public keys rather than trusting the
client. The real blocker is only that a valid Firebase ID token cannot be
minted from a shell.

Practical consequence: this IS exercisable on a device today. The installed
11:46 APK reaches `/auth/google` on prod, so a real Google signup with a fresh
account would confirm the behaviour — no config change needed.

---

## 2026-08-25 — Cart storage scoped to the customer (UNCOMMITTED, batch 6)

customer_app only. Backend, owner_app and admin_app untouched — zero files
modified in any of them. Folds into the SAME pending review as the five batches
already queued.

### The bug

`carevo_cart_v1` was ONE global `SharedPreferences` key
(`cart_state.dart:40`, pre-change). Logout cleared the session token
(`auth_state.dart:166`) and nothing else, so the next account to sign in on the
device inherited the previous customer's basket, the outlet it was bound to, and
the "Continue where you left off" banner naming that restaurant. Reproduced
before fixing: a brand-new account with zero orders landed on the FIRST-RUN home
screen carrying `2 items from Meenakshi Bhavan`.

It leaked through memory AND disk: the `CartState` instance is built in `main()`
above `MaterialApp`, so it outlives a logout that only swaps the navigator
stack, and the blob outlives the process.

### Scoping the store, not patching the call sites

The key is now `carevo_cart_v1_<customer id>`, with `carevo_cart_v1_guest` for
logged-out. `customers.id` (`Customer.id`, `models/customer.dart:18`) is the
scope — the same identifier the API authorises against.

Clearing the cart inside `logout()` was rejected: it fixes the paths that go
through logout and misses the ones that do not, and the diagnostic found two
that do not — a **Google sign-in over a live session**
(`auth_state.dart:139-160`) and **401 session loss**
(`_onSessionLost`, `auth_state.dart:21-25`), which fires from a background
request with no screen mounted. All five identity-change paths do share one
thing: they assign `AuthState._customer` and notify. New
`state/cart_identity_sync.dart` binds there — a single listener, so a future
auth flow is covered the day it is written.

`CartState.setIdentity` flushes queued writes BEFORE switching scope, and
`_persist()` now captures its KEY synchronously alongside the payload.
Without that, a write queued moments before a switch lands under the incoming
customer's identity — the same leak by a slower route. Pinned by its own test.

`CartIdentitySync` serialises re-scopes rather than firing them in parallel: one
auth call notifies several times (`AuthState` toggles `busy` around assigning the
customer), and two concurrent `setIdentity` calls can both pass its
already-on-this-scope guard, since it awaits a flush before assigning.

**A null customer is not "guest".** On a cold start with a restored token the
customer is null until `/customer/me` returns — the session exists, its identity
is merely unresolved. Treating that as a sign-out would blank a basket that is
about to be restored, so an authenticated-but-unresolved session is left alone.

### Guest cart: DISCARDED at sign-in, never merged

Stated because it must not be left undefined. A merge is the same
identity-boundary crossing this fix exists to stop: on a shared device it hands
whoever signs in next the previous person's items — the reported bug in a new
costume. A prompt was rejected too: it puts a question to the customer that the
app is in a better position to answer, at the worst possible moment. Nothing
durable is lost (a cart is one outlet's items, re-validated at checkout anyway),
and the guest state is currently unreachable in practice — the splash routes an
unauthenticated launch straight to login and every catalog endpoint requires a
customer token. The guest blob is deleted when a real identity takes over, so it
cannot linger for the next logged-out person.

### The legacy blob is deleted, not migrated

A device upgrading from a pre-scoping build has a `carevo_cart_v1` that records
no owner. It is removed at `restore()`. Adopting an unattributable basket into
whoever opens the app next IS the bug. Cost: a customer upgrading mid-basket
loses those items once.

### Tests

New `test/cart_identity_scope_test.dart`, 14 tests: the key scheme (3), the five
identity paths as five isolated tests, the two-account reproduction from the
diagnostic (including a widget test asserting B's Home has no resume banner and
no trace of A's outlet), A getting A's own cart back, the guest policy (2), and
the in-flight-write boundary.

customer_app **228** (was 214), owner_app **1**, backend **147** untouched and
not re-run — no backend file was modified. `flutter analyze` clean.

**Revert proof, both halves independently:**

* un-scope the key (`storageKeyFor` returns one shared key) → **10 of 14 fail**
* disable the sync (`CartIdentitySync.start()` returns early) → **12 of 14 fail**,
  including all five identity paths and the Home widget test

13 of the 14 fail under one revert or the other. The one that fails under
neither is the legacy-blob test, which pins a third behaviour neither revert
touched.

Files: `lib/state/cart_state.dart`, `lib/main.dart`,
new `lib/state/cart_identity_sync.dart`, new `test/cart_identity_scope_test.dart`.

---

## 2026-08-25 16:59 IST — Sideload APK built from the six pending batches

Build only — no source change, nothing committed. Built from the working tree
carrying all six uncommitted customer_app batches (filter/card-size, location
permission ×3, login redesign, name-capture gating, guard removal, and the
cart-identity scoping above).

```
app-release.apk   57,923,608 bytes   2026-08-25 16:59:39 IST
sha256 4EC201A2993F401851FD15B9D3CBF6935BF938AFDD27115BDE4956D5DCD32F96
sha1   45DE9C0A3AF081C3041093B653DE8210EB966DB0  (matches the .sha1 sidecar)
```

`--dart-define=FORCE_RECAPTCHA_FLOW=true`, as every sideload build: Play
Integrity cannot vouch for a sideloaded install, so without the override phone
auth dies at `17028` and no SMS is sent. **The committed default is untouched** —
`app_config.dart` still reads `defaultValue: false` and `pubspec.yaml` is still
`1.0.0+3`, both confirmed by an empty `git diff` before AND after the build. Only
this artifact carries the flag.

Replaces the 12:30:32 APK (`F57837FE…`, 57,890,840 bytes), which predated the
cart-identity work. Gradle `assembleRelease` 70.1s, exit 0.

**The override cannot be verified statically** — a `--dart-define` compiles into
the AOT Dart snapshot. The only proof it took effect is behavioural: sign-in
raises the reCAPTCHA webview and an SMS arrives.

Build warnings, none fatal and all pre-existing: `flutter_google_places_sdk_android`
still applies the Kotlin Gradle Plugin, 32 packages held back by constraints,
MaterialIcons tree-shaken 1,645,184 → 9,360 bytes.

Outside the Play versionCode lineage — this is a sideload artifact, not an
upload candidate.

---

## 2026-08-25 — BACKFILL: three backend commits landed without their log entries

**Flagged as backfilled, not contemporaneous.** Recorded here so the gap is
visible rather than silently closed.

The standing rule (2026-08-11) is that every commit carries its own `carevomd.md`
entry *inside that commit*. Three backend commits broke it:

| Commit | Pushed | What it did |
|---|---|---|
| `520794cd` | 08-24 16:20 | Multi-city outlet filter (`lower(city) = ANY(...)`, one bound param), `OutletOut.created_at` added to back the Newest sort, and `get_menu` stopped filtering `is_available` so sold-out items arrive flagged instead of vanishing. 5 files, 181+/21−. Deploy confirmed 16:23:53 by the `/openapi.json` schema flip. |
| `b984bd69` | 08-25 11:41 | `is_new_account` returned from both auth routes, so a name typed at signup could win over a Google profile name. 3 files, 39+/7−. Deploy confirmed 11:41:16, purely additive (`default: false`, `required` unchanged). |
| `6df95351` | 08-25 12:22 | Stopped seeding `customers.name` from the Google `name` claim — `PATCH /customer/me` is now the ONLY writer. 1 file, 17+/7−. Deploy NOT confirmable: `/openapi.json` is byte-identical because no signature changed, and there is no version endpoint. |

The fuller entries for all three DO exist above in this file — they were written
after each push rather than included in it, and have been sitting uncommitted
ever since. They land with the commit this entry belongs to. So the record is
complete from here on; it simply was not complete *at the time*, and no future
reader should infer from the file's contents that it was.

Root cause worth keeping: the entries were written at the end of each deploy
verification, by which point the commit had already been made and pushed. The
rule only works if the entry is written BEFORE staging, not after pushing.

---

## 2026-08-25 — customer_app: six batches land

One commit, six batches of work built across 2026-08-24 and 08-25 and held at
the user's instruction for a single diff review. Backend, owner_app and
admin_app are untouched — zero files modified in any of them.

The per-batch entries above stay as the detailed record; this entry is what the
commit itself carries.

### What is in it

1. **Filter button + card size** — the outlet list's sort/filter affordance and
   card geometry. `outlet_sort.dart` holds the options AND their ordering rules
   so "what does this sort do" and "does it work" cannot drift; three sorts are
   real (Nearest, Newest, Best Offers) and seven carry a `blockedBy` string
   naming the missing signal, rendered greyed with "Coming soon" and inert three
   independent ways. No rating or review data exists to fake them from.
2. **Location permission ×3** — a dedicated permission dialog, an on-resume
   re-check so a grant made in system Settings is noticed without a restart, and
   the checkout "Use my location" path. `LocationService` still raises at most
   one prompt per grant state, and no automatic caller may spend it.
3. **Login redesign** — the identifier field and OTP entry reworked; the
   email/phone auto-detect was removed rather than reshaped.
4. **Name-capture gating** — `post_auth_router.dart` is now THE single post-auth
   decision point: a signup goes to `NameCaptureScreen`, a returning sign-in
   goes to Home. This replaced a second gate inside `HomeScreen.build` that
   fired on "name is empty" — two gates on two conditions is how someone gets
   asked twice. A legacy account with no name deliberately is NOT trapped.
5. **Guard removal** — the client half of `6df95351`. `is_new_account` now
   decides only whether to SHOW the name screen; it no longer referees between
   two writers of `customers.name`, because the second writer is gone.
6. **Cart identity scoping** — `carevo_cart_v1` was ONE global key, so a logout
   that cleared only the session token left the next account to sign in holding
   the previous customer's basket, outlet, and "Continue where you left off"
   banner. The key is now `carevo_cart_v1_<customer id>`, with a separate
   `guest` scope; `CartIdentitySync` re-scopes on every identity change from a
   single listener on `AuthState`, because two of the five paths
   (Google-over-a-live-session, 401 session loss) never reach `logout()` at all.

### Verified against

```
app-release.apk   57,923,608 bytes   2026-08-25 16:59:39 IST
sha256 4EC201A2993F401851FD15B9D3CBF6935BF938AFDD27115BDE4956D5DCD32F96
```

Built with `--dart-define=FORCE_RECAPTCHA_FLOW=true` (sideload; Play Integrity
cannot vouch for a sideloaded install). `pubspec.yaml` stays `1.0.0+3` and
`app_config.dart` stays `defaultValue: false` — both confirmed by an empty
`git diff` before and after the build, so only that artifact carries the flag.
It is outside the Play versionCode lineage and is not an upload candidate.

### Device testing — Adi, first-hand, 2026-08-25

**Adi installed the `4EC201A2…` APK on his own phone and ran the cart-isolation
checks himself. This section is his first-hand observation, recorded as his, and
is deliberately kept separate from the machine-verified evidence below** — the
agent writing this file had no device attached at any point (`adb devices` empty
on every check) and watched none of it happen.

What he confirmed working:

* **Fresh-account isolation.** Account A adds to cart at an outlet, logs out,
  signs up as a brand-new account B. B shows **no resume banner, no leftover
  cart items, and no reference to A's outlet.**
* **Google account switch with NO logout step.** Switched from account A
  straight to a different Google account without logging out first. Same result
  — the cart re-scoped correctly, nothing leaked.

That second one is the important one, and it is why the fix binds to
`AuthState`'s customer rather than to `logout()`: it is the path a
clear-the-cart-on-logout repair would have missed entirely, and it has now been
exercised on a real device rather than only in a test harness.

### Machine-verified, separately

Batch 6 carries 14 tests: all five identity-change paths in isolation, the
two-account reproduction (including a widget test asserting B's Home carries no
resume banner and no trace of A's outlet), the guest-cart policy, and the
in-flight-write boundary — plus two independent reverts, one un-scoping the key
(10 of 14 fail) and one disabling the sync (12 of 14 fail).

### Tests at time of commit

customer_app **228 passed, 0 failed** (was 186 before these batches began).
owner_app **1**. Backend **147**, not re-run — no backend file is in this commit.
`flutter analyze` clean.

### Deliberately NOT in this commit

`owner_app/pubspec.yaml` (`+1` → `+2`), held back since the 08-21 decision:
owner_app is sideloaded, not distributed through Play, so its versionCode has no
Play constraint to reconcile against and the bump is its own decision.
`.claude/settings.local.json` (local tool permissions), `.env` (untracked and
gitignored), `UI_REDESIGN_HANDOFF.md`, `design/`, `pdf/`, the loose gif/mp4/jpeg
files at the repo root, and the ~16,631 deleted MAUI `bin`/`obj` artifacts.

Per the standing rule, this entry cannot cite its own commit hash — amending the
entry in changes it. Take the live hash from the push.

---

## 2026-08-26 15:25 IST — PRE-RESTART SNAPSHOT (known-good baseline)

Recorded deliberately before a planned machine restart, so the next session's
re-orientation check has something exact to diff against rather than
reconstructing the tree from memory. **Nothing was committed, built or changed
to produce this entry** — it is a reading of the tree, not a change to it.

### Git position

```
branch          21_7
HEAD            70871cf6  feat(customer_app): six UI/UX batches + per-customer cart scoping
origin/21_7     70871cf6      (0 ahead, 0 behind — fully pushed)
index           EMPTY — nothing staged
tracked files   17,639
```

No merge/rebase/cherry-pick in progress; no `index.lock`.

### Uncommitted tree — what SHOULD be there on next boot

**The walking-footer batch (5 files) — the only real work in flight:**

```
 M customer_app/lib/screens/home_screen.dart      (footer at the bottom of both Home variants)
 M customer_app/pubspec.yaml                      (assets: block ONLY; version untouched at 1.0.0+3)
?? customer_app/assets/animation/final_walk.gif   (3,356,566 bytes)
?? customer_app/lib/widgets/walking_footer.dart
?? customer_app/test/walking_footer_test.dart
```

**Two long-standing modified files, both deliberately held back:**

```
 M .claude/settings.local.json   local tool permissions, never staged
 M owner_app/pubspec.yaml        +1 -> +2, held since the 2026-08-21 decision:
                                 owner_app is sideloaded, not on Play, so its
                                 versionCode has no Play constraint to reconcile
```

**Long-standing untracked docs and assets (18):** `UI_REDESIGN_HANDOFF.md`;
`design/` (4: `.thumbnail`, two `.dc.html` prototypes, `support.js`); `pdf/` (3);
`customer_app/assets/icon/play_store_icon_512.png`;
`customer_app/assets/marketing/` (7: feature graphic + 6 store screenshots);
and at the repo root `final_walk.gif`, `walk.gif`, `guy_walking.jpeg`,
`generate_a_gif_and_video_of_th.mp4`.

**Plus 16,631 deleted MAUI `bin`/`obj` artifacts** under `gusto_pos/GustoPOS` and
`gusto_pos/GustoWaiter`, from the 2026-08-12 disk cleanup. Long-standing;
restorable with `git checkout` or by rebuilding.

**`gusto_pos/backend` and `admin_app` are COMPLETELY clean — 0 entries each.**

### Open item carried into the next session

Phone OTP sign-in fails on the `D64B37E0…` sideload. Root cause was captured in
logcat at 00:06:27 on 2026-08-26 and is NOT what earlier entries assumed: the Keystore
cannot load Firebase Auth's Tink master key
(`FirebearCryptoHelper: Keystore cannot load the key with ID: firebear_master_key_id.…`),
so `RecaptchaActivity` cancels before rendering, the SDK explicitly "calls
backend without app verification", and the backend refuses with 17093 — which
surfaces as the user-visible "missing a valid app identifier". The dart-define
worked: `RecaptchaActivity` only runs on the forced path, and the app's own
`Could not force reCAPTCHA flow` never fired. So the fault is device-local
crypto, not SHA fingerprints, Firebase console config, or the backend.

Capture: `scratchpad/logcat_auth_20260826-0003.log`, failure chain at lines
3735-3747. **Scratchpad is session-temporary and will not survive the restart** —
the chain is quoted above precisely because that file is about to disappear.

Device: Nothing A142P, Android 16, stock (`user` / `release-keys`), Play Services
26.32.34, `remote_provisioning.strongbox.rkp_only=1`. Wireless ADB was at
`192.168.1.4:45311`; that port is reassigned every time Wireless debugging is
toggled, so it will need re-reading off the phone next time.

### Note on this entry itself

Appending it makes `carevomd.md` show as ` M` — so on next boot the expected
count is **6 modified files, not 5**. That is this entry, and nothing else.

---

## 2026-08-26 16:47 IST — CORRECTION to the 15:25 snapshot's counts (labels only)

The entry directly above is **correct in every file it names and wrong in two of
the numbers it labels them with**. Read on restart, its file-level enumeration
matched the tree exactly — path for path, plus HEAD `70871cf6`, 17,639 tracked,
16,631 MAUI deletions, empty index, backend and `admin_app` clean, and
`final_walk.gif` byte-exact at 3,356,566. Nothing was lost or altered across the
restart. **Only the arithmetic in the prose was wrong.** Per the append-only rule
the original text is left untouched; this entry supersedes its two counts.

### What was mislabeled

```
"6 modified files, not 5"          ->  5 modified          (entry, closing note)
"untracked docs and assets (18)"   ->  20 long-standing    (entry, body)
"22 untracked"                     ->  23 untracked        (carried into the
                                                            re-orientation brief)
```

The `(18)` is contradicted by the entry's own list on the same lines, which
enumerates 20: `UI_REDESIGN_HANDOFF.md` (1) + `design/` (4) + `pdf/` (3) +
`play_store_icon_512.png` (1) + `assets/marketing/` (7) + 4 repo-root media
files. Trust that list, not its label.

### Correct decomposition

```
MODIFIED = 5
  2   walking-footer batch    home_screen.dart, customer_app/pubspec.yaml
  1   carevomd.md             the snapshot entry itself
  2   held back               .claude/settings.local.json, owner_app/pubspec.yaml

UNTRACKED = 23
  3   walking-footer batch    assets/animation/final_walk.gif,
                              lib/widgets/walking_footer.dart,
                              test/walking_footer_test.dart
 20   long-standing           as enumerated above

TOTAL porcelain -uall = 16,659  =  16,631 deleted + 5 modified + 23 untracked
```

### Root cause of both bad numbers

A double-count of the same three files. The walking-footer batch is **5 files,
but only 2 of them are modified** — the other 3 are new and therefore untracked.
Counting all 5 as modified inflates the modified total (5 + carevomd + 2 held
back = 8 by that reading; the entry's own "6" is a partial version of the same
slip) and drops those 3 out of the untracked total. Whenever this log quotes a
batch size, check whether the files are `M` or `??` before adding it to either
column.

Nothing was committed, built, or changed to produce this entry — like the one
above it, it is a correction to the record, not to the tree.

---

## 2026-08-26 18:12 IST — Walking footer: letter overlay dropped, plain loop kept

The initial-on-the-shirt overlay is **abandoned**. `WalkingFooter` now draws the
walk cycle and nothing else — no text, no `Stack`, no per-frame position table,
and no read of `customer.name` or `AuthState` at all. 336 lines down to 155.

### Why — a design decision, not a bug fix

On-device the letter sat wrong. The code was then checked and **found correct**:

* frame 0's table entry `Offset(0.43616, 0.45343)` is 34.3% of figure height,
  inside the 22%-44% chest band, and all 70 entries land in-band (32.9%-34.7%);
* frame 0 is not an outlier — its wrap-neighbour steps are 3.49px (56th pct)
  and 5.24px (94th pct, only the 4th largest of 70), on the same smooth trace;
* re-measuring the GIF from scratch reproduced the shipped table (y correlation
  0.836, vertical travel 16.25px measured vs 16.2px documented);
* the widget's index default before decode is 0, which is genuinely the first
  decoded frame's index — the assumed value and the real one agree;
* rendering frame 0 with the letter position marked puts it mid-torso.

So the reported misposition was never reproduced off-device and **its root cause
was never found**. The overlay was dropped rather than chased: it is decoration,
and it was not worth more time than it had already taken. Recording this plainly
because the deleted table was correct work — if the letter is ever wanted back,
start from the fact that the measurements were sound and the fault lay somewhere
downstream of them, not in the table.

One real defect was found on the way and is now moot: the letter was drawn
whenever a name existed but the figure only once `_image` was non-null, so
during the pre-decode window the letter floated with no man behind it.

### Also changed

The inter-frame `Future.delayed` is now a cancellable `Timer` + `Completer`,
released in `dispose()`. It previously kept ticking up to 70ms after the widget
was gone — harmless in the app, fatal to a widget test ("a Timer is still
pending after the widget tree was disposed"). Pre-existing, not introduced here.

### Tests

15 letter/table tests deleted, 11 written: first frame renders, the box holds
its size before decode so Home does not jump, the animation advances, it loops
(stepped 75 frames past the 70-frame clip), dispose mid-playback is clean, it
renders with no provider in the tree, it draws no `Text`, and the sizing rules
hold at 320/400/800/90. Suite 243 -> 239, all passing, `flutter analyze` clean.

These decode the **real GIF** — with the letter gone the frame index is no
longer observable from outside, so the old test seam went with it. Note for
whoever touches them: playback starts in `initState`, so its timer lives in the
test's fake-async zone and only moves when the clock is pumped. Waiting in real
time will not advance it.

`shirt_stability.py`, which `walking_footer.dart` used to cite for regenerating
the table, never existed in the repo — it lived in a scratchpad that a restart
destroyed. That reference is gone with the table.

---
