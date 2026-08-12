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
