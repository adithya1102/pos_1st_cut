# Reconciliation layer — operator runbook

Branch `reconcile` (from `payment-tab`). Everything in this layer is
additive and OFF by default — a deploy that sets no new env var behaves
exactly as `payment-tab` did.

## Billing eligibility, per payment mode

`charge_if_eligible` (`app/modules/carevo_payments/fee_ledger.py:70-72`)
writes a `CHARGE` row for exactly one condition, applied uniformly to
every mode: `customer_orders.status = 'COMPLETED'` (line 70, via
`_BILLABLE_STATUSES = {"COMPLETED"}` at line 40) **AND**
(`customer_orders.payment_status = 'PAID'` **OR**
`customer_orders.vendor_payment_confirmed_at IS NOT NULL`) (line 71).
What differs per mode is only WHICH function sets `payment_status =
'PAID'`, and when, relative to the `COMPLETED` write:

| Mode | Completion path (status → `COMPLETED`) | Payment-confirmed condition | Charged |
|---|---|---|---|
| `PREPAID` | `CarevoService.verify_pickup` — `app/modules/carevo_customer/service.py:4243` (def), write at line `4343` | `payment_status = 'PAID'`, set by `CarevoService.mark_paid` — `service.py:2779` (def), write at line `3003` (the gateway webhook/simulate path, BEFORE the order ever reaches pickup) | **YES** |
| `UPI_MANUAL` | `CarevoService.verify_pickup` — `service.py:4243`, write at line `4343` (the non-gateway money guard at `service.py:4320-4335` refuses this transition unless `payment_status` is already `'PAID'`) | `payment_status = 'PAID'`, set by `CarevoService.record_pickup_payment` — `service.py:5084` (def), write at line `5138` — called from `AcceptanceService.accept` — `app/modules/carevo_customer/acceptance.py:233` (def), call site at line `377-378`, with `at_counter=False` (staff checked their own UPI app at ACCEPT time, before pickup) | **YES** |
| `PAY_AT_PICKUP` | `CarevoService.collect_order` — `service.py:5170` (def), write at line `5248` | `payment_status = 'PAID'`, set by the SAME `CarevoService.record_pickup_payment` (`service.py:5084`/`5138`), called from `collect_order` itself with `at_counter=True`, in the SAME transaction as the `COMPLETED` write | **YES** |
| any mode, vendor-direct gateway | `reconciliation.apply_vendor_payment_event` (Task 5) | `vendor_payment_confirmed_at IS NOT NULL`, set at `reconciliation.py` on an `APPLIED` outcome — orthogonal to `payment_mode` | **YES** |
| `CANCELLED` / `ABANDONED` (rejected, expired, no-show) | none — `status` never reaches `COMPLETED` for these; see `_TERMINAL_STATUSES`, `service.py:89` | n/a | **NO** |
| refunded after completion | `AdminService.mark_refund_done` (`app/modules/carevo_admin/service.py`) | a REVERSAL is written for an already-charged order, not a charge refusal — the charge was correct when written; the refund is a later fact (migration 041's header) | **NO** (new charge); existing charge is reversed |

**Status per mode: STATED for all three (`PREPAID`, `UPI_MANUAL`,
`PAY_AT_PICKUP`).** None contradicts "charged when `COMPLETED` and
payment is confirmed (gateway-paid, vendor-confirmed, or collected at
pickup)" — no code change was needed. `CANCELLED`/`ABANDONED` orders
never reach `COMPLETED` at all (status is one value, structurally
exclusive), so they are excluded without a separate check;
`manual_refund_due` (the restaurant's own direct-UPI refund obligation)
is written only alongside `status = 'CANCELLED'` in this codebase (inside
`reject_order`), so it can never co-occur with a `COMPLETED` order either.

## Fix pass (post-independent-review)

An independent review of this branch found several defects, since fixed
in their own commits:

- **The service fee was never actually charged.** `fee_ledger.
  charge_if_eligible` had no caller anywhere in `app/` — it is now called
  inside `CarevoService.verify_pickup` and `CarevoService.collect_order`,
  the only two code paths that ever set `customer_orders.status =
  'COMPLETED'`, in the SAME transaction as that status change
  (`commit=False`, with an explicit `db.flush()` first so the ledger's own
  re-read sees the pending ORM write). A ledger failure now rolls back the
  whole completion/handover with it. Likewise `fee_ledger.
  reverse_if_charged` is now called from `AdminService.mark_refund_done`,
  the one "mark an order refunded" action in this codebase.
- **The billable status is `'COMPLETED'` only.** `'PICKED_UP'` is never
  written to `customer_orders.status` anywhere in this codebase
  (`CarevoService.record_picked_up` explicitly does not move
  `order.status`) — it was a dead literal in the old billable set and in
  migration 041's header comment, both corrected.
- **`payment_events.event_id` is never NULL.** A provider delivery with no
  event id of its own (a signed Cashfree FAILED/PENDING webhook with no
  `cf_payment_id`) now falls back to `"body:" + sha256(raw body)` instead
  of hitting a NOT NULL violation that the old blanket
  `except IntegrityError` mislabelled DUPLICATE — the event is recorded
  (IGNORED/REVIEW as appropriate), not silently dropped. Only a genuine hit
  on `uq_payment_events_provider_event` (Postgres SQLSTATE `23505` on that
  exact constraint) is now reported as DUPLICATE; any other integrity
  error re-raises.
- **`amount_paise` is validated before any UPDATE.** Not a plain positive
  `int` within Postgres `integer` range (so: no bool, no float, no string,
  no `<= 0`, no `> 2147483647`) routes to `REVIEW`/`AMOUNT_INVALID` instead
  of either a mismatch or an uncaught `DataError` mid-transaction.
  `confirm`/`reject` on a `payment_events` row now only act when its
  outcome is `REVIEW` and it has not already been resolved by a prior
  confirm/reject (checked against `admin_audit_logs`); anything else is
  `409` with no audit row written.
- **`RazorpayWebhookAdapter`'s verification logic is fixed to match real
  Razorpay deliveries.** The fabricated `X-Razorpay-Event-Timestamp`
  requirement (a header real deliveries never send) is removed; only
  `X-Razorpay-Signature` is required. Idempotency event id comes from
  `x-razorpay-event-id`, falling back to the same body-hash scheme above
  when absent. Replay defence is `payment_events`' own dedup, not a
  header this provider does not document. `production_eligible` STAYS
  `False`, deliberately — matching the documentation is not the same
  claim as having been proven against a real delivery, and no real
  Razorpay delivery has been observed by this adapter yet. See
  `docs/runbooks/PROVIDERS.md` for the full verification record and the
  exact bar that flips this flag to `True`.
- **The vendor webhook route now logs a reason code on every rejection**
  (`flag_off` / `unknown_outlet` / `credential_error` /
  `adapter_unavailable` / `signature_invalid`, plus the provider name —
  never a body, signature, secret, ciphertext, or key id), and the
  unknown-outlet path now does the same decrypt-and-HMAC work the
  known-outlet-wrong-signature path does, so the two are not
  distinguishable by timing either.

## New environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRETS_ENC_KEY` | unset | AES-256-GCM key, urlsafe-base64, decodes to exactly 32 bytes. Required before `VENDOR_GATEWAY_ENABLED=true` can start (fail-closed, see below). |
| `SECRETS_ENC_KEY_ID` | unset | Label for the key above, carried inside every ciphertext so a later key can be introduced without losing the ability to decrypt rows written under the old one. Required alongside `SECRETS_ENC_KEY`. |
| `VENDOR_GATEWAY_ENABLED` | `false` | Master switch for `POST /api/v1/webhooks/{provider}/{outlet_id}` and the admin credential-rotation route. `404` on the webhook route while false. |
| `SERVICE_FEE_LEDGER_ENABLED` | `false` | Master switch for the Rs 1 service-fee ledger (`charge_if_eligible` / `reverse_if_charged` are no-ops while false). |
| `SERVICE_FEE_PAISE` | `100` | The fee charged per eligible order, in paise. |
| `RAZORPAY_ADAPTER_ENABLED` | `false` | Enables `RazorpayWebhookAdapter` in the adapter registry. Stays `production_eligible=False` regardless — see `docs/runbooks/PROVIDERS.md`; this flag only matters for tests until that gap is closed. |

None of these is read by anything in `payment-tab` — every one is a brand
new `Settings` field with a default that preserves today's behavior.

## Key-generation command (run this yourself, at your own terminal — never share the output)

```
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Run it once per key. The printed value is `SECRETS_ENC_KEY`; pick any short
label of your own (e.g. `k1`) for `SECRETS_ENC_KEY_ID`. Nothing in this
repository ever prints, logs, or stores this value anywhere except as
ciphertext.

## Render + Neon deploy order

1. **Migrations 039, 040, 041 first**, against Neon, before any new code
   deploys. All three are `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT
   EXISTS` / `CREATE OR REPLACE FUNCTION` — safe to run against the live
   database with the CURRENT `payment-tab` code still running, since no
   existing query names any of the new tables/columns/functions yet.
   Migration 041 additionally runs `CREATE EXTENSION IF NOT EXISTS
   pgcrypto` — confirm the Neon role deploying has privilege to create
   extensions (the project owner role does by default).
2. **Deploy the code** in this branch. With every new flag still at its
   default (`false`), this is a no-op deploy: no new route answers
   anything but `404` (`VENDOR_GATEWAY_ENABLED`), no new write path runs
   (`SERVICE_FEE_LEDGER_ENABLED`), and `/admin/reports/daily` /
   `/admin/payment-events/*` simply exist and work (they are not
   flag-gated themselves, since they are read-only or human-decision
   routes with no money-moving effect).
3. **Set `SECRETS_ENC_KEY` / `SECRETS_ENC_KEY_ID`** on Render as soon as
   you intend to ever turn `VENDOR_GATEWAY_ENABLED` on — the app refuses
   to start with that flag true and no usable key
   (`app.core.secrets_box.assert_startup_ready`, called from
   `app/main.py`'s `on_startup`).
4. **Turn flags on one at a time, per the pilot pattern this codebase
   already uses for `CASHFREE_ONLY`** — e.g. `SERVICE_FEE_LEDGER_ENABLED`
   on its own first (it only writes an audit ledger, no customer-facing
   change), then `VENDOR_GATEWAY_ENABLED` once at least one outlet has a
   credential set via `PUT /admin/vendor-gateway/outlets/{id}/
   credentials/{provider}`.

## Neon connection strings

The app passes `settings.DATABASE_URL` straight to `create_async_engine()`
(`gusto_pos/backend/app/core/database.py:34-36`) with no `connect_args` and
no SSL override anywhere in that call. `DATABASE_URL` is a required,
untyped string field (`app/core/config.py:7`) — nothing in this codebase
validates its scheme or query string before handing it to the driver. The
driver is `asyncpg` (`gusto_pos/backend/requirements.txt:8` pins
`asyncpg==0.31.0`; the local example in `.env.example:5` already uses the
`+asyncpg` scheme).

NO EVIDENCE in this codebase of an explicit `ssl=`/`sslmode=` default —
whatever query string is in `DATABASE_URL` reaches the driver unmodified.
The application and `psql` need two different forms of the same Neon
string, because `sslmode` is a libpq/`psql` convention and the `asyncpg`
driver does not accept a `sslmode` keyword (it raises `TypeError: connect()
got an unexpected keyword argument 'sslmode'` if one reaches it):

- **Application (async engine, `asyncpg` driver)** — scheme
  `postgresql+asyncpg://`, query parameter `ssl=require` (NOT `sslmode`):
  `postgresql+asyncpg://<user>:<password>@<host>/<db>?ssl=require`
- **`psql` (libpq)** — scheme `postgresql://` (no `+asyncpg`), query
  parameter `sslmode=require` (NOT `ssl`):
  `postgresql://<user>:<password>@<host>/<db>?sslmode=require`

**Exact edit from a Neon-issued string.** Neon's dashboard issues
connection strings already in the second (libpq/`psql`) form above. To
produce the first (application) form from that same string:
1. Insert `+asyncpg` after `postgresql` → `postgresql+asyncpg://...`.
2. Replace `sslmode=require` with `ssl=require` in the query string.

Host, database name and credentials are identical between the two forms —
only the scheme and the one query parameter name change. Never paste the
credential portion of a real connection string into this or any other
runbook — only the placeholder shape above.

## Startup table creation

`init_db()` (`gusto_pos/backend/app/core/database.py:40-42`) is a no-op:

    async def init_db():
        """No-op — schema is managed by reset_db.py."""
        pass

It creates NONE of the tables from migrations 039, 040 or 041
(`payment_events`, `outlet_gateway_credentials`, `service_fee_ledger`) —
and it creates none of the pre-existing base tables either. Schema creation
for every table in this codebase, old and new, happens only through the
numbered `migrations/*.sql` files (applied by hand against Neon) or through
`tests/reset_test_db.py` (local `carevo_test` only).

**Consequence for deploy order: migrations before code, always.** Nothing
in `app/main.py`'s startup path (`on_startup`, `main.py:119-164`) creates a
missing table or column. A code deploy that reads or writes
`payment_events`, `outlet_gateway_credentials` or `service_fee_ledger`
before migrations 039-041 have been applied against the target database
fails at the first query that touches one of them, not at startup — there
is no code-side fallback that builds the schema for you. This is the reason
step 1 of "Render + Neon deploy order" above runs the migrations before
step 2 deploys the code, not the other way around.

## Rollback

Each migration has a paired rollback script:
- `docs/ops/039_payment_events_rollback.sql`
- `docs/ops/040_outlet_gateway_credentials_rollback.sql`
- `docs/ops/041_service_fee_ledger_rollback.sql`

All three are safe to run before the corresponding flag is ever turned on
anywhere. Once real rows exist (a webhook was verified, a fee was charged),
running a rollback is a deliberate data-loss decision, not a routine
revert — say so explicitly before running one against Neon.

Code rollback is a plain `git revert`/redeploy of the prior commit; nothing
in this layer alters any existing table's existing columns or any existing
route's existing behavior, so reverting the code with the migrations still
applied is also safe (the new tables/columns simply go unread again).

## Known limitations

- **Confirm/reject on a REVIEW payment_events row does not re-run the
  original skipped effect.** `POST /admin/payment-events/{id}/confirm`
  and `.../reject` (Task 7) write only an `admin_audit_logs` row recording
  the human decision and reason. Building the matching effect-application
  (e.g. actually crediting a cross-outlet payment to the correct order, or
  re-checking an amount-mismatch against a corrected total) would need the
  same logic `reconciliation.apply_vendor_payment_event` already has,
  re-entered from a human decision instead of a webhook delivery — not
  attempted in this pass.
- **`RazorpayWebhookAdapter`'s optional `created_at` window check is
  unverified against Razorpay's documentation** — WebFetch could not
  confirm (or rule out) a top-level `created_at` field in the webhook
  payload envelope after four attempts. The check is best-effort only: it
  never rejects for the field's absence, only for its presence plus an
  out-of-window value. See `docs/runbooks/PROVIDERS.md`. (The adapter's
  prior production-blocking gap — the fabricated timestamp HEADER
  requirement — is fixed; see "Fix pass" above.)
- **`RazorpayWebhookAdapter.production_eligible` is `False`, and stays
  that way, until a real sandbox delivery has been observed end to end.**
  The verification logic matching Razorpay's documentation is a
  different, weaker claim than having actually been exercised against a
  genuine delivery — this codebase has never received one. See
  `docs/runbooks/PROVIDERS.md` for the exact observation that flips the
  flag.
- **The daily report's `failed`/`pending` counts only reflect
  `payment_events` rows** (i.e. vendor-gateway deliveries, Task 5). The
  pre-existing CareVo-mediated Cashfree/stub flow
  (`/customer/payment/webhook`) does not write to `payment_events` — a
  failed or pending payment through THAT path is not counted here. Only
  `verified_payments` and `eligible_orders` read `customer_orders`
  directly and so cover both paths.
- **`outlet_gateway_credentials` rotation keeps exactly one row per
  (outlet, provider).** There is no history of prior secrets, by design
  (the old plaintext is unrecoverable the moment a rotation commits) —
  but this also means there is no audit trail of WHEN a secret was last
  rotated beyond the single `rotated_at` timestamp on that row.

## Provider status

| Provider | Existing code | Sandbox done | Merchant onboarding | Production credentials | Production eligible |
|---|---|---|---|---|---|
| Cashfree | Yes (`CashfreeGateway`, pre-existing; `CashfreeAdapter` wraps it, Task 3) | Yes (this repo's existing sandbox flow, pre-existing) | **Rejected at onboarding, production not available** | No | No — platform-level Cashfree is rejected; the vendor-direct model (Task 5) uses a VENDOR's own Cashfree merchant account and secret, never CareVo's |
| Razorpay | Yes (`StubRazorpayGateway`, pre-existing stub; `RazorpayWebhookAdapter`, Task 3, verification logic fixed in the post-review pass) | Stub only — no real sandbox credentials exercised in this task | Not attempted | No | No (`production_eligible=False`, deliberately kept — the fabricated timestamp-header gap is closed, but no real sandbox delivery has been observed end to end yet; see `docs/runbooks/PROVIDERS.md` for the exact bar) |

Row-for-row, this table says the same thing the business rules in this
task required going in: **no provider is assumed approved**, and nothing
built in this reconciliation layer depends on Cashfree's platform-level
approval status.

Status: **DONE**, four counts: **1406 / 0 / 0 / 1** (tests / failures /
errors / skipped) — the original 1279, plus 83 from Tasks 2–7, plus 44
from the post-review fix pass (new wiring/validation/visibility tests
plus the net change to the Razorpay section of
`test_api_webhook_adapters.py`), all passing; the one skipped is the same
pre-existing xfail recorded in `docs/reports/RECON_BASELINE.md`.
