# Reconciliation layer — operator runbook

Branch `reconcile` (from `payment-tab`). Everything in this layer is
additive and OFF by default — a deploy that sets no new env var behaves
exactly as `payment-tab` did.

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
- **`RazorpayWebhookAdapter`'s replay-timestamp check is unverified
  against real Razorpay traffic.** It reads a header
  (`X-Razorpay-Event-Timestamp`) that Razorpay's own documentation does
  not describe; a genuine Razorpay webhook would fail this check today.
  See `docs/runbooks/PROVIDERS.md`. This is why the adapter stays
  `production_eligible=False` regardless of `RAZORPAY_ADAPTER_ENABLED`.
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
| Razorpay | Yes (`StubRazorpayGateway`, pre-existing stub; `RazorpayWebhookAdapter`, Task 3, net-new) | Stub only — no real sandbox credentials exercised in this task | Not attempted | No | No (`production_eligible=False`; see Known Limitations) |

Row-for-row, this table says the same thing the business rules in this
task required going in: **no provider is assumed approved**, and nothing
built in this reconciliation layer depends on Cashfree's platform-level
approval status.

Status: **DONE**, four counts: **1362 / 0 / 0 / 1** (tests / failures /
errors / skipped) — the original 1279 plus 83 new tests across Tasks 2–7,
all passing; the one skipped is the same pre-existing xfail recorded in
`docs/reports/RECON_BASELINE.md`.
