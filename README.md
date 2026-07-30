# CareVo Skip

_Project status — last verified against deployed state + code on 2026-07-30 (branch `21_7`, HEAD `e4347fd7`)._

## Overview

CareVo Skip — a customer pre-order/pickup pilot app built on the existing **GustoPOS**
stack. Customers browse nearby restaurants, order ahead, pay via UPI, and skip the
queue by picking up with a verified code. Ships with:

- **customer_app** — the customer-facing ordering app
- **owner_app** — restaurant staff tool (menu, orders, payment confirmation, pickup verify)
- **admin_app** — CareVo super-admin dashboard (outlet approval, moderation, audit)

## Architecture

| Component | Stack | Deployment |
|---|---|---|
| Backend | FastAPI + async SQLAlchemy, PostgreSQL (**Neon**) | Render → https://gusto-pos-backend.onrender.com (`/docs`) |
| customer_app | Flutter, neobrutalist/retro design | debug APK (side-loaded) |
| owner_app | Flutter, Material 3 | debug APK (side-loaded) |
| admin_app | Next.js (React 19, TS) | Render → https://carevo-admin-dashboard.onrender.com |

- **Branch:** all work lives on **`21_7`** — never merged to `main` or `14_july`.
- **CI:** `.github/workflows/admin-ci.yml` runs `npm ci && npm run build` on
  `ubuntu-latest` / Node 22 for every `21_7` push touching `admin_app/`, catching
  cross-platform lockfile drift before Render deploys.
- CareVo backend modules live under `gusto_pos/backend/app/modules/`:
  `carevo_customer` (customer + payment + owner-POS service logic), `carevo_pos`
  (staff-authed POS routes), `carevo_admin` (super-admin), `onboarding` (public
  `/register`). Migrations are additive raw SQL under `migrations/` (001–005); **no
  Alembic**. WebSocket notify layer is **in-memory** (no Redis).

## What's working (verified against deployed backend / current schema)

- **Staff auth** — `POST /api/v1/auth/login` (username/password). Both **owner_app**
  and **admin_app** reuse this single mechanism; admin access is gated by the
  `SUPER_ADMIN` role.
- **Customer OTP auth** — ⚠️ **currently ENABLED** as a temporary test-window setting
  (`CUSTOMER_AUTH_ENABLED=true`), running in stub mode: any phone + OTP **`000000`**
  logs in. **While enabled this is an open login for anyone with the URL/APK.** A
  scheduled cloud job is set to revert it to `false` on **2026-08-01**; until then,
  keep APK distribution to known testers. (When disabled, `/customer/auth/*` returns
  503 and there is no real OTP provider wired.)
- **Menu CRUD** — add/edit/delete (soft-deactivate) dishes with name, price, category,
  **veg/non-veg**, prep time, and **image (Cloudinary unsigned upload)**. All routes
  are outlet-scoped and ownership-guarded.
- **Categories** — new self-registered outlets are seeded with a default set
  (Starters, Mains, Sides, Desserts, Beverages) so the dish picker has options
  immediately. (See limitations re: custom categories.)
- **Outlet visibility toggle** and **per-dish availability toggle** (owner_app).
- **Restaurant onboarding** — self-serve (**owner_app** pre-login "Register your
  restaurant") and admin-assisted (**admin_app** "Onboard restaurant"), both calling
  the same public rate-limited `POST /register`. New outlets land as
  **`pending_verification`** (hidden from customers) until an admin approves them.
  Each collects a required per-outlet **UPI ID**.
- **Pickup flow** — order → payment → **`pickup_code`** (6 chars, digits **2–9** only,
  ambiguity-safe) → **TTL auto-expiry** (a PAID/live order untouched for
  `PICKUP_TTL_MINUTES` = **45 min** auto-transitions to `ABANDONED`, freeing its code
  for reuse; check-on-read, no scheduler) → staff verification in owner_app (3-strike
  lockout → HTTP 423) → `COMPLETED`.
- **Notify system** — one-directional staff→customer pushes (`ready_now`,
  `delayed_10`, `item_unavailable`) over the in-memory WS channel; customer_app shows
  a read-only banner.
- **UPI Intent payment** — raw `upi://pay` deep link built from the outlet's stored
  `upi_id` (payee), order total (amount, locked), and order id (tracking ref); opens
  the user's UPI app. **No automated confirmation** — staff tap **"Mark Payment
  Received"** in owner_app (`POST /pos/orders/{id}/mark-paid`), which flips the order
  to PAID, issues the pickup code, and surfaces it to the customer.
- **Admin dashboard** — pending-outlet approval/reject queue, all-outlets view,
  locked-order unlock, audit log, and admin-assisted onboarding.

## Known limitations / NOT built yet

- **Wait-time / ETA logic is NOT built.** There is no distance calculation, no
  mode-of-transport input, no "leave by" recommendation, and no prep-time +
  travel-time combination anywhere in the codebase. **The 45-min pickup_code TTL is a
  cleanup mechanism, NOT a wait-time estimate — do not conflate the two.**
- **Google Maps integration** (Distance Matrix ETA + Places Autocomplete + a
  customer_app browse-by-locality filter) — **blocked on a Maps Platform API key +
  billing**, not started. Localities are currently free-text.
- **Payment is raw UPI Intent only** — no payment gateway (e.g. Cashfree) integration,
  no automated payment confirmation. The backend has a stub/razorpay-shaped gateway
  abstraction (`PAYMENT_GATEWAY=stub`) but no real gateway is wired. Expect bank/UPI
  risk-engine friction on new payee relationships during testing.
- **Custom per-restaurant categories are NOT built.** Owners select from seeded
  categories only — there is no endpoint or UI for an owner to create/rename their own
  categories yet. (Planned; pending.)
- **OCR menu upload** — not built.
- **No wallet / stored-value feature** — deliberately deferred (regulatory complexity).
- **Free-tier hosting** — both Render services sleep after ~15 min idle (~50s cold
  start); the first request after idle can look like a timeout.

## Known issues / things to watch

- **admin_app `NEXT_PUBLIC_*` env vars are baked at BUILD time.** Changing one requires
  **Manual Deploy → "Clear build cache & deploy"**, not a restart — a plain redeploy
  can ship the stale/absent value (which surfaces as "Failed to fetch" against
  `localhost`). This cost multiple sessions to diagnose. Verify by checking the
  deployed JS chunks actually contain the backend URL.
- **Debug APKs need a full uninstall before reinstalling** across major changes — the
  signing key, baked URL, or `AndroidManifest` `<queries>` (UPI visibility) can change,
  and an in-place overwrite may not pick them up. Uninstall, then install fresh.
- **owner_app `HomeState` is a singleton** that survives logout; category loading now
  always refetches to avoid serving a previous outlet's data. Watch for similar
  cross-session state leaks if adding more cached lists.

## For a new agent session picking this up

- **Read `AGENT_GUARDRAILS.md` first** — mandatory operating rules: prod-vs-dev-branch
  DB identification (Neon `ep-...` host), Checkpoint A (schema/migration approval) and
  Checkpoint B (git commit/push approval), fixture discipline (`TEST_CAREVO_` prefix +
  proven teardown), and what already exists (do not rebuild).
- **Do not trust this README as live state** — check the **task tracker and recent
  git commits** for the actual current state before assuming anything here is still
  accurate. It will drift (e.g. the `CUSTOMER_AUTH_ENABLED` toggle and its revert date).
- Secrets live in env, never committed: `gusto_pos/backend/.env` (gitignored);
  Render dashboard env for `DATABASE_URL`/`SECRET_KEY` (`sync:false`) and
  `NEXT_PUBLIC_API_URL`; `admin_app/.env.local`.
