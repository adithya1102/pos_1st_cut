# Isolation map — the Cashfree money fixes

Scope: the three defects fixed in `CarevoService.mark_paid` and the webhook
controller (`gusto_pos/backend/app/modules/carevo_customer/service.py`,
`controller.py`), per `test_api_cashfree_hardening.py`'s own docstring. For
each: exact files, the commit that introduced it, and whether it DEPENDS on
migrations 034–038 or on the `CASHFREE_ONLY` switch, with the evidence.

All three landed in a single commit:

```
2fd3d6d9 feat(backend): CASHFREE_ONLY switch, Cashfree webhook hardening, scheduled-release feasibility gate
```

Landing in the same commit as the `CASHFREE_ONLY` switch and migration 038 is
**not** evidence of a dependency on either — each fix is checked below
against what it actually reads/writes at runtime, not against what else the
commit happened to bundle.

---

## 1. The amount check (underpaid webhook)

**Files:**
- `gusto_pos/backend/app/modules/carevo_customer/service.py` —
  `CarevoService.mark_paid`, lines 2905–2927 (the `UNDERPAID` branch).
- `gusto_pos/backend/app/modules/carevo_payments/gateway.py` —
  `WebhookEvent.amount_paise` field and `CashfreeGateway.parse_webhook`'s
  paise conversion (the data the check compares against).
- `gusto_pos/backend/migrations/038_payment_amount_mismatch.sql` — the two
  columns the check writes to.

**Commit:** `2fd3d6d9`

**Migration dependency: DEPENDS on migration 038.**
Evidence: the branch at service.py:2920–2925 executes
`UPDATE customer_orders SET payment_amount_mismatch = true,
payment_amount_mismatch_at = now() WHERE id = :id`. Both columns are created
by migration 038 and by nothing else — `grep -rn payment_amount_mismatch
migrations/` matches only `038_payment_amount_mismatch.sql`. Running this
code against a database that has not applied 038 raises `UndefinedColumn` on
the first underpaid webhook.

**CASHFREE_ONLY dependency: INDEPENDENT.**
Evidence: the branch is reached from `mark_paid`, which is called by both
`/customer/payment/webhook` (any live gateway, `CASHFREE_ONLY` on or off) and
`/customer/payment/simulate` (stub only). Nothing in the branch, or in
`mark_paid`'s signature, reads `settings.CASHFREE_ONLY`. The only reason it
is a no-op under the stub today is that `/payment/simulate` passes no
`amount_paise` (the stub carries no amount) — `grep -n CASHFREE_ONLY
service.py` shows zero hits inside `mark_paid`.

---

## 2. The late-payment refund-queue handling

**Files:**
- `gusto_pos/backend/app/modules/carevo_customer/service.py` —
  `CarevoService.mark_paid`, lines 2862–2903 (the terminal-status branch).

**Commit:** `2fd3d6d9` (the branch at this call site; the columns it writes
predate this commit — see below).

**Migration dependency: INDEPENDENT of 034–038 — depends on migration 032
instead, already applied before this fix existed.**
Evidence: the branch at service.py:2891–2897 executes
`UPDATE customer_orders SET refund_required = true, refund_reason =
'late_payment_after_expiry', refund_flagged_at = now() ...`. All three
columns originate in `migrations/032_refund_and_manual_acceptance.sql`
(`grep -rn refund_required migrations/` — first hit is 032, confirmed by
that file's own header: "customer_orders.refund_required / refund_reason /
refund_flagged_at"). None of 034–038 adds, alters, or is read by this branch.
`grep -n refund_required migrations/034*.sql migrations/035*.sql
migrations/036*.sql migrations/037*.sql migrations/038*.sql` returns only
comment references, no column definitions.

**CASHFREE_ONLY dependency: INDEPENDENT.**
Evidence: same call site as fix 1 — reached from `mark_paid` regardless of
`CASHFREE_ONLY`, gated only on the order's own status being terminal and
`pickup_mode` not being a non-gateway method (`PAY_AT_PICKUP`/`UPI_MANUAL`,
which have no gateway payment to refund in the first place). No reference to
`settings.CASHFREE_ONLY` anywhere in the branch.

---

## 3. The unknown-order-id log

**Files:**
- `gusto_pos/backend/app/modules/carevo_customer/controller.py` —
  `payment_webhook`, lines 628–634 (the `logger.warning(...)` call and the
  `404` it precedes).

**Commit:** `2fd3d6d9`

**Migration dependency: INDEPENDENT.**
Evidence: the fix is a `logger.warning` call naming `evt.our_order_id`,
`evt.gateway_order_id`, `evt.gateway_payment_id`, and `evt.outcome` — all
fields already present on `WebhookEvent` (`gateway.py`), a plain Python
dataclass with no database-backed fields at all. No column, table, or
migration is touched or required for this line to run. Verified by
`test_api_cashfree_hardening.py::TestUnknownOrder`, which asserts on
`caplog.text` alone with no database assertion.

**CASHFREE_ONLY dependency: INDEPENDENT.**
Evidence: the log line sits immediately before `raise HTTPException(404, ...)`
in the branch reached when `order is None` — i.e. any webhook (from any live
gateway) naming an order id that does not resolve. This is upstream of
anything `CASHFREE_ONLY` gates (which affects which payment *methods* are
offered at order creation, not whether an already-arrived webhook can be
traced). `grep -n CASHFREE_ONLY controller.py` returns zero hits anywhere
near this function.

---

## Summary table

| Fix | Files | Commit | Depends on 034–038? | Depends on `CASHFREE_ONLY`? |
|---|---|---|---|---|
| Amount check | `service.py:2905-2927`, `gateway.py` (`WebhookEvent.amount_paise`, `CashfreeGateway.parse_webhook`) | `2fd3d6d9` | **DEPENDS** — migration 038 (`payment_amount_mismatch[_at]`) | INDEPENDENT |
| Late-payment refund queue | `service.py:2862-2903` | `2fd3d6d9` (branch); columns from migration 032 | INDEPENDENT of 034–038 (depends on pre-existing migration 032) | INDEPENDENT |
| Unknown-order log | `controller.py:628-634` | `2fd3d6d9` | INDEPENDENT | INDEPENDENT |

No cherry-pick, merge, or push was performed to produce this document — it
is read-only analysis of the `cashfree-only` branch's existing history.
