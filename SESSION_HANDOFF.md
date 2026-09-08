# CareVo / GustoPOS — Session Handoff
Compiled 2026-08-11, for continuing work in Claude Code CLI or a fresh chat
context. This supersedes the 2026-08-10 handoff — the two bugs it listed as
"immediate priorities" are now fixed and confirmed.

**Important — this document has no access to referenced file contents.**
It describes what those files contain and why they matter, but the actual
text is not reproduced here. If a new session needs the full content of any
of the following, they must be uploaded/attached manually:
- `AGENT_GUARDRAILS.md` (repo root — likely already accessible if the new
  session has repo access, e.g. Claude Code CLI; not accessible if this is
  a plain chat with no file access)
- `carevo-timing-engine-master_v1.0` (the full wait-time/scheduling design doc)
- `carevo-timing-engine-addendum-v1.1.md` (the follow-up covering train mode,
  cold-start JIT fallback, ITEM_UNAVAILABLE cutoff)
- The 2026-08-08 Current-State Inventory (`GustoPOS_CareVo_Current_State_Inventory`,
  a live-DB-verified technical audit — more reliable than any model.py or
  CLAUDE.md claim, per multiple confirmed cases of code/schema drift)

**Mandatory reading order for any new agent session with repo access, before
touching code:**
1. `AGENT_GUARDRAILS.md` — Checkpoint A (migration diff approval before
   schema changes hit prod) and Checkpoint B (full changed-file approval
   before any git push). Non-negotiable, "full freedom" on any task never
   waives these.
2. This file.
3. The timing engine master + addendum docs, if the task touches
   wait-time/scheduling logic.
4. The Current-State Inventory, for anything schema/API/architecture related.

---

## 1. Standing risk — still unresolved, fix opportunistically
- **`gusto_pos/backend/.env` with live prod Neon credentials is committed to
  git, unrotated.** Confirmed via the 2026-08-08 inventory audit. Nothing
  since has rotated it.
- Most legacy dine-in routes (`/customers/*`, `/users/*`, `/roles/*`,
  `/orders/*`, `/outlets/*` CRUD, etc.) are unauthenticated on the public
  internet, including mutating verbs. All 5 WebSocket channels have zero
  auth. `/ws/order/{order_id}` will stream another customer's order status
  to anyone who knows the UUID.
- These were scoped as part of a pre-launch security pass but have not been
  confirmed fixed in any session since — treat as still open.

## 2. System shape — two parallel order systems, one API
- **Legacy dine-in path** (`orders`, `order_items`, `payments`, `tables`,
  `table_sessions`, etc.) — all 0 rows in prod as of last check. Built for
  GustoPOS (Windows MAUI) and GustoWaiter (tablet MAUI), both still
  hardcoded to a LAN IP (`192.168.1.6:8000`), not pointed at Render.
- **CareVo Skip path** (`customer_orders`, `customer_order_items`,
  `payment_transactions`, `order_events`, `order_twin`, `order_outcome`,
  `prediction_log`, `outlet_reliability`) — carries all live data. Still
  dev/test volume — CareVo has not publicly launched.
- Repo: `C:\Users\Adithya\Desktop\demo2`, branch `21_7`. Backend on Render
  free tier (sleeps ~15 min idle). Apps: `customer_app` (Flutter,
  "CareVo Skip"), `owner_app` (Flutter, "CareVo Owner"), `admin_app`
  (Next.js, SUPER_ADMIN dashboard).
- Kitchen timing is currently **synthetic**: `ORDER_ACCEPTED`/`PREP_STARTED`
  are inferred from payment (`source='inferred'`) — every outlet still sits
  at `trusted_order_count=0`. The owner app has no UI to fire real
  kitchen-stage taps despite backend support. This is a known, accepted gap
  the Timing Engine addendum's Item 2 partially addresses (see §5).
- Unresolved architecture question, not blocking: should GustoPOS become the
  authoritative system reading/writing CareVo Skip's order data, or does
  CareVo Skip stay on its own model with GustoPOS just reading it? Legacy
  `orders.source` column looks designed for exactly this unification but was
  never wired that way.

## 3. Fixed and confirmed since the last handoff
Both items that were "immediate priorities" in the 2026-08-10 handoff are
now done and confirmed working by the user on a real device:

1. **Order/OTP persistence bug — FIXED.** The pickup code screen
   (`PickupScreen`) is now reachable two ways: an active-order banner on the
   outlets screen, and a split "In progress" / "Past orders" view in Order
   History. Both a plain back-press and the "Order more"/"Back to orders"
   action now correctly return to the app rather than destroying the nav
   stack (this took two commits — `d936fe85` then a follow-up fix
   `ba8aa427`, since the first pass silently missed one button's logic).
   Confirmed by the user testing the full flow on-device.
2. **Admin "Orders" tab — BUILT and confirmed.** New, separate tab (not
   merged into the existing per-customer Customers tab, which is untouched)
   showing one row per order: customer name/phone/email, dishes, order ID,
   pickup OTP, outlet, timestamp, total paid, promotion name + discount,
   and distance (km) from customer to outlet (null when GPS origin was
   never captured, never fabricated). Paginated. User confirmed data is
   displaying correctly.

## 4. Next priority — Timing Engine addendum v1.1
Now that the two app-level bugs are resolved, this is next, in this order:

1. **Item 3 (cheap, ship first):** `ITEM_UNAVAILABLE` may only be marked
   before that item/order reaches `READY` — enforce server-side (reject the
   write) and client-side (disable the control), not just as a
   documentation note.
2. **Item 2 (highest-priority fix):** cold-start JIT prep-scheduling
   fallback. Fires when `trusted_order_count(outlet) < 30` AND
   `hold_tolerance_seconds(order) < 300`; delays `PREP_STARTED` eligibility
   using a fixed buffer from existing cuisine-category pool defaults
   (master doc §11.3/§11.4). Does NOT unlock the departure-window display —
   only gates when the kitchen may start. Populates `order_twin`'s
   `scheduled_prep_start_at`/`latest_safe_start_at` (currently never
   written by any code path — confirmed via direct code search, not
   assumed). Emits `PREP_SCHEDULED`. **A prior investigation found there is
   no existing JIT scheduling system to extend — this is genuinely
   build-new, not extend-existing. It was also found to collide with the
   "mark_paid stays exactly as-is" decision (§5 below) as literally
   specified**, so a smaller re-scoped version was proposed (shadow-mode
   event emission only, changes nothing about when food is actually cooked)
   — **this re-scope was reported to the user but not yet explicitly
   approved as of this handoff.** Confirm before building.
3. **Item 1 (blocked):** add `train` as a transport mode. **Blocked on a
   decision the user has not yet made**: data source for train ETA — a live
   rail API, a static timetable for known pilot routes, or a customer-
   entered manual arrival time as the cheapest v1 fallback. Do not assume
   an answer.
4. **Item 4 (doc-only):** multi-modal journey chaining (train+auto,
   bike+train, etc.). Explicitly do NOT build — document the reasoning in
   the master doc's "what not to build yet" section only.

Also flagged during the addendum review, not yet acted on:
- The kitchen-timing formula (`predict_kitchen`, `PredictionService`)
  computes one `μ_ready` assuming all stations start simultaneously — no
  per-station stagger logic. Confirmed as a real modelling gap, not a live
  bug today (nothing currently acts on kitchen timing, so nothing is
  affected yet) — but it will become a real defect the moment Item 2 or any
  JIT system lands, since `order_twin` schema has one scheduled-start
  column per *order*, not per *station*. Needs its own scoping before
  Item 2 goes further than the shadow-mode version.
- `FR-M3` (one promise revision, none after customer departure) has an open
  question: what happens on a *second* kitchen slip that occurs *before*
  departure, when no revisions are left? Not yet decided.

## 5. Recent decisions (condensed — don't re-litigate without new info)
- **Payments**: Cashfree integrated (0% commission until March 2027,
  sandbox keys currently active, `PAYMENT_GATEWAY=cashfree` live on Render).
  UPI Intent removed entirely (was structurally broken — depended on a
  manual "Mark Payment Received" action that no longer exists). ZohoPay
  planned as a later switch (0.5% + wallet) via the same gateway-factory
  abstraction. Refunds stay manual/out-of-app in V1. **New unresolved
  consequence**: money now lands in the CareVo merchant account, not each
  restaurant's `upi_id` (which is now unused by payment flow) — no
  settlement/payout process to actually pay restaurants exists yet. Not
  urgent with test data, but must be solved before any real restaurant is
  onboarded.
- **Order acceptance**: auto-accept by default — payment success alone
  (via webhook) triggers acceptance, `mark_paid` unchanged (still emits
  inferred `ORDER_ACCEPTED`/`PREP_STARTED`), no human gate. Only a manual
  **Reject** action exists (`ORDER_REJECTED` event, status → `CANCELLED`),
  available any time before `READY`. Staff get a push on every new paid
  order regardless of app state.
- **Item availability**: owner_app order-detail view shows items as a
  checklist; staff can mark item(s) N/A in one batch action, each
  triggering its own instant customer notification. "Reorder" opens a
  fresh, separate order — does not modify the original paid order (ties to
  the manual-refund decision above).
- **Promotions**: two distinct types — CareVo Campaigns (admin-created,
  CareVo-funded) vs Restaurant Offers (owner-created, restaurant-funded,
  auto-surfaced, optional shareable code). Item-linked promos ("combo_offs")
  explicitly out of V1.
- **Push notifications**: FCM wired for both apps (customer_app and
  owner_app), service-account credential in place on Render. Staff get
  `STAFF_NEW_ORDER` on every paid order; customers get order-status and
  item-unavailable pushes. Last confirmed status: pipeline fires correctly;
  live delivery to a real device was pending final confirmation as of the
  last check.
- **Auth**: Google Sign-In and phone OTP both live via Firebase, standalone
  (no auto-merge between a phone identity and a Google identity for the
  same person). `CUSTOMER_AUTH_ENABLED=false` (correct, permanent — the old
  stub-OTP bypass is closed), `FIREBASE_ENABLED=true`. One incident on
  2026-08-06 where a scheduled cloud job unexpectedly flipped
  `FIREBASE_ENABLED` to false, breaking login — fixed manually, root cause
  in the job itself not fully confirmed; worth rechecking if this job is
  still scheduled to recur.
- **Owner account recovery**: change-password fully working. Forgot-password
  mechanism built correctly (identical-response security pattern, masked
  email hint, admin-queue fallback for accounts with no email) but actual
  email *delivery* is not wired — no mail provider (Resend/SendGrid/SES)
  configured, `EMAIL_ENABLED=false`.
- **Account deletion**: implemented as anonymization, not hard delete —
  hard delete is structurally impossible given `RESTRICT` foreign keys from
  `order_events`/`customer_orders` back to `customers` (deleting would
  destroy restaurants' own revenue records). Identity fields overwritten
  with a `deleted:<uuid>` tombstone; order/ledger rows retained without PII.
- **Play Store**: personal developer account (not Organization — D-U-N-S
  route confirmed slower than just doing 14-day closed testing). Only
  `customer_app` goes to Play Store; `owner_app` stays sideloaded. Release
  upload keystore generated and backed up (WhatsApp, Telegram, Drive,
  local folder). `targetSdkVersion`/`compileSdkVersion` already at 36
  (Android 16), compliant. Testers are known SWEs (Oracle, Wells Fargo,
  Microsoft, NVIDIA, Mu Sigma), using existing seeded test outlets +
  Cashfree Sandbox, transparent that it's pre-launch/simulated. Real
  restaurant recruitment comes after production access, using the approved
  app as proof-of-product. **Still outstanding**: Play Console account
  signup/verification, privacy policy hosting (draft exists at
  `customer_app/PRIVACY_POLICY.md`, placeholders need filling + needs a
  live URL), account-deletion in-app flow (built per above, confirm it
  satisfies Play's requirement), content rating questionnaire, data safety
  form, store listing assets, closed testing track creation.
- **Testing infrastructure**: a real automated backend/API test suite now
  exists (pytest + httpx, isolated local `carevo_test` database, 57 passing
  tests as of last count) — structurally cannot pollute prod, unlike a
  session earlier that left 5 permanent test rows in prod's append-only
  event log despite trying to clean up. Run this suite for any backend
  regression check going forward rather than testing new logic directly
  against prod.
- **Pre-launch priority order** (still governing): (1) secure the system,
  (2) make existing workflows reliable, (3) get the event/data foundation
  correct, (4) ensure the first real transaction produces clean attributable
  data, (5) explicitly NOT building the full personal-agent/vector/
  cross-restaurant-learning architecture yet.

## 6. Open decisions awaiting the user — don't assume an answer
- Train-mode data source for the timing engine (§4, Item 1).
- Item 2's re-scoped (shadow-mode-only) proposal — reported, not yet
  explicitly approved.
- Whether GustoPOS should become the write-path of record for CareVo Skip
  orders, or stay read-only against `customer_orders` (§2).
- Settlement/payout process for restaurants now that Cashfree centralizes
  payment collection (§5).
- The FR-M3 second-slip notification gap (§4).

## 7. How Claude Code should operate on this repo
- Follow Checkpoint A/B from `AGENT_GUARDRAILS.md` exactly — migration diff
  approval before any schema change hits prod, full changed-file approval
  before any git push to `21_7`.
- Prefer raw SQL for anything touching CareVo-path tables — the ORM models
  are stale (multiple tables have columns the ORM doesn't know about, and
  at least one live column, `menu_items.tags`, has no model or migration
  behind it at all — confirmed via the automated test suite's bootstrap
  process). Don't trust `model.py` over `information_schema`.
- Distinguish prod branch (`ep-...` hostname) from any dev/test branch
  before running anything with write access. A local `carevo_test` database
  now exists specifically so schema/logic changes can be tested without
  touching prod — use it.
- User (Adi) operates as a PM-level coordinator, not a hands-on coder —
  expect to work from detailed prompts/specs rather than being handed code
  directly.
- This project has repeatedly benefited from agents that verify claims
  against the live system (curl probes, direct DB queries, grepping built
  binaries) rather than trusting their own or a prior report — several real
  bugs this project (a silently-incomplete UI fix, a migration that didn't
  actually apply, a config check that read the wrong source) were only
  caught this way. Continue that discipline.

---

## Prompt for Claude Code (paste this as your first message in the new session)

> This repo is CareVo Skip / GustoPOS (branch `21_7`). Before doing anything,
> read `AGENT_GUARDRAILS.md` at repo root in full, then read
> `SESSION_HANDOFF.md` (also at repo root — copy it in if it's not there
> yet) for full project context, recent decisions, and current priorities.
> Confirm you've read both and summarize the current priority (§4, the
> Timing Engine addendum) and the two open decisions blocking parts of it
> (§6) before we start. Follow Checkpoint A and Checkpoint B exactly as
> defined in the guardrails for any schema change or git push — no
> exceptions, no matter how the task is framed.
