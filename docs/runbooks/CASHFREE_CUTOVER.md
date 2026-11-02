# CASHFREE_ONLY cutover runbook

Cutting one outlet over to Cashfree as its only payment path. This document
is the authority for the order of operations; the actual SQL lives in
`docs/ops/cashfree_only_cutover.sql`, `docs/ops/cashfree_only_cutover_rollback.sql`
and `docs/ops/cashfree_only_verify.sql` (all three are referenced, not
duplicated, below).

Scope note, stated once and binding for the whole document: **the YOUPI
gateway, its edge key, and the `youpi_observer` SMS app are out of scope.**
`origin/youpi-trial` is a separate, abandoned payment-trial branch and is
**never merged** into this cutover. Nothing in this runbook reads, builds, or
deploys anything from that branch.

---

## 1. Migration order

Apply in this numeric order — each is additive and safe to run on a live
database (no `UPDATE`/`DELETE` of existing rows, see each file's own header
for its rollback):

| # | File | Adds |
|---|------|------|
| 034 | `migrations/034_pay_at_pickup.sql` | `outlets.payment_prepaid_enabled`, `outlets.payment_pay_at_pickup_enabled`, `outlets.call_window_s`, `customer_orders.payment_mode` + contact/call columns, `customers.no_show_count` |
| 035 | `migrations/035_manual_upi_and_owner_settings.sql` | `outlets.cashfree_unlocked`, UPI VPA columns, owner self-serve settings route support |
| 036 | `migrations/036_cashfree_default_locked.sql` | Flips the **default** of `outlets.cashfree_unlocked` to `false` for future inserts only — no existing row changes |
| 037 | `migrations/037_outlet_owner_marker.sql` | `users.is_outlet_owner` |
| 038 | `migrations/038_payment_amount_mismatch.sql` | `customer_orders.payment_amount_mismatch`, `payment_amount_mismatch_at` |

### Why 034–037 are required for this cutover (not optional, not skippable)

The cutover's entire effect is flipping two columns for one outlet
(`payment_prepaid_enabled`, `cashfree_unlocked`) and having the running code
already know how to read them. If any of 034–037 is missing, the columns the
cutover writes to do not exist, or the code paths that gate on them cannot
resolve correctly:

- **034** (`outlets.payment_prepaid_enabled`) and **035**
  (`outlets.cashfree_unlocked`) are read TOGETHER by
  `CarevoService.payment_methods_for`
  (`gusto_pos/backend/app/modules/carevo_customer/service.py`, ~line
  1263–1294): PREPAID is only ever offered when `prepaid_on AND
  cashfree_unlocked AND` the gateway reports `is_live`. Without 034 or 035,
  this cutover's `UPDATE` has no column to write.
- **036** matters for every outlet *other* than the one being cut over today:
  it is what makes a brand-new outlet start with Cashfree **locked**
  (`cashfree_unlocked=false`) rather than silently inheriting the old
  `true` default. Skipping it means every new signup after this point is
  Cashfree-unlocked by accident.
- **037** (`users.is_outlet_owner`) gates who may change an outlet's payment
  settings at all — read in `app/modules/carevo_pos/deps.py:85`
  (`may_manage_outlet_settings`). Without it, the owner self-serve
  payment-settings route (the UI path an owner would otherwise use instead of
  this SQL runbook) has no authorization check to key on.
- **038** (`customer_orders.payment_amount_mismatch[_at]`) is not required
  for the column flip itself, but it is required for **safe Cashfree
  operation once prepaid is the only path**: `CarevoService.mark_paid`
  (service.py ~line 2922–2923) uses it to flag a webhook that reports PAID
  for less than the order total, rather than marking the order PAID anyway.
  Cutting an outlet to Cashfree-only without 038 reinstates the short-payment
  gap this migration closed.

Run `docs/ops/cashfree_only_verify.sql` query 1 to confirm all of the above
columns exist on the target database before proceeding.

---

## 2. Render environment variable names (names only — no values recorded here)

Set in the Render dashboard's Environment tab for the `gusto-pos-backend`
service, **never** in `render.yaml` (secrets are `sync: false` there by
design — see that file's header comment):

**The switch:**
- `CASHFREE_ONLY` — not yet declared in `render.yaml` at all; this cutover is
  what adds it. Set to `true` only after every step below is complete.

**Already-required Cashfree selector/credentials** (must already be correct
before `CASHFREE_ONLY` is ever set `true` — `validate_cashfree_only_config`,
`app/core/config.py`, refuses to start the process otherwise):
- `PAYMENT_GATEWAY` (must equal `cashfree`)
- `CASHFREE_APP_ID`
- `CASHFREE_SECRET_KEY`
- `CASHFREE_ENV` (`sandbox` or `production`)
- `CASHFREE_NOTIFY_URL`

---

## 3. Order of operations

1. **Residue check** (read-only, required before anything else touches a
   production copy): run `docs/ops/trial_residue_check.sql` against a COPY
   of the production database — never production itself. Review every
   returned row **with the owner, outlet by outlet**, and for each row record
   a decision: **KEEP** (a genuine order/payment that must survive the
   cutover) or **ARCHIVE** (YOUPI trial residue that must not appear in
   production reporting). This file already exists, is read-only, and its
   own trailing comment block repeats this same procedure — follow it
   verbatim; do not edit its queries.
2. Confirm migrations 034–038 are applied on the target database (verify.sql
   query 1).
3. **Rehearsal**, on a **fresh copy of the production database** — explicitly
   **not** the old `youpi-trial` copy, which carries residue this cutover is
   designed to leave behind:
   - Restore the fresh copy.
   - Run `docs/ops/cashfree_only_cutover.sql` against it end-to-end, with a
     real outlet id substituted for the placeholder.
   - Run `docs/ops/cashfree_only_verify.sql` against the same copy and
     confirm the expected state.
   - Run `docs/ops/cashfree_only_cutover_rollback.sql` and confirm it cleanly
     reverses the change.
   - Discard the rehearsal copy once satisfied — it is never promoted to
     production.
4. **Sandbox checklist**, using the **owner's own Cashfree sandbox keys**
   (never CareVo's or a shared test account):
   - [ ] `CASHFREE_APP_ID` / `CASHFREE_SECRET_KEY` in the dashboard are the
         owner's sandbox pair, `CASHFREE_ENV=sandbox`.
   - [ ] Place one real order against the outlet being cut over and confirm
         the Cashfree checkout sheet opens (not the stub path — see
         `render.yaml`'s own incident note on `PAYMENT_GATEWAY`).
   - [ ] Complete a sandbox payment and confirm the webhook moves the order
         to `PAID` with a pickup code.
   - [ ] Confirm `payment_transactions.gateway = 'cashfree'` for that order.
   - [ ] Only after all of the above: swap in the owner's **production**
         Cashfree keys and set `CASHFREE_ENV=production`.
5. **The real outlet cutover:**
   - Run `docs/ops/cashfree_only_cutover.sql` against production, with the
     real outlet id substituted for `<OUTLET_ID>`. It runs in one
     transaction and prints a before/after snapshot — read both before
     committing.
   - Set `CASHFREE_ONLY=true` in the Render dashboard (only after step 4 is
     fully signed off; the process refuses to start with `CASHFREE_ONLY=true`
     and a misconfigured gateway/credentials — see
     `validate_cashfree_only_config`).
   - Redeploy / restart the service so the new environment variable takes
     effect.
6. **First hour** — watch, using `docs/ops/cashfree_only_verify.sql`:
   - Query 3: every order this outlet takes should show
     `payment_mode = 'PREPAID'`.
   - Query 4: every payment transaction for this outlet should show
     `gateway = 'cashfree'`.
   - Query 5: `payment_amount_mismatch` rows — a short payment needing manual
     reconciliation against the Cashfree dashboard.
   - Query 6: `refund_required` rows — a late payment that arrived after the
     order/stock hold already went terminal (expected occasionally, not a
     bug — see `CashfreeGateway.expiry_seconds`'s own documentation of this
     window).
   - Watch for pay-at-pickup or UPI-manual orders appearing for this outlet
     at all — in `CASHFREE_ONLY` mode `payment_methods_for` should never
     offer either, so any such order is a sign the switch did not take.
7. If anything in step 6 is wrong, run
   `docs/ops/cashfree_only_cutover_rollback.sql` immediately — it re-locks
   Cashfree for this one outlet in one transaction, independent of the
   `CASHFREE_ONLY` environment variable (which is a platform-wide switch, not
   a per-outlet one).

---

## 4. Punctual scheduled release needs an always-on instance

`render.yaml` currently runs `gusto-pos-backend` on `plan: free`. Render's
free tier sleeps after ~15 minutes idle and takes the `auto_advance_poller_loop`
background task with it (`app/modules/testing_dashboard/service.py`). A
scheduled (held) order's release is then only as punctual as the next request
that happens to wake the service, or the one-time startup catch-up
(`catch_up_overdue_releases`, same file) that runs when the service restarts —
neither is a substitute for the poller actually running every
`AUTO_ADVANCE_POLL_SECONDS`. **Before relying on scheduled pickup for a
Cashfree-only outlet in production, upgrade the Render service off the free
plan to an always-on instance.** This is a prerequisite for correctness of
scheduled release timing, not a performance nicety.

---

## 5. Out of scope

- The YOUPI gateway, its edge key, and the `youpi_observer` SMS app are not
  touched, read, or referenced by this cutover beyond identifying their
  residue via `docs/ops/trial_residue_check.sql`.
- `origin/youpi-trial` is never merged, rebased onto, or cherry-picked from.
  This cutover is entirely local to the `cashfree-only` branch's own code and
  the production database's `outlets`/`customer_orders` tables.
