# Reconciliation Inventory — payment-tab @ 8bb85585 (branch `reconcile`)

Read-only audit. No code changed to produce this file. Every later task builds
ONLY what is marked PARTIAL or NOT BUILT below; BUILT items are not rewritten.

| Item | Status | File : function |
|---|---|---|
| Webhook signature verification | BUILT | `gusto_pos/backend/app/modules/carevo_payments/gateway.py` — `StubRazorpayGateway.verify_webhook_signature` (fails closed, no secret/signature → `False`), `CashfreeGateway.verify_webhook_signature` (base64 HMAC-SHA256 over `timestamp+body`, fails closed) |
| Replay protection | BUILT | `gusto_pos/backend/app/modules/carevo_customer/controller.py` : `payment_webhook` — rejects a missing/non-numeric `x-webhook-timestamp` and one outside `settings.CASHFREE_WEBHOOK_MAX_AGE_S` (default 7200s) |
| Payment event idempotency | BUILT | `gusto_pos/backend/app/modules/carevo_customer/service.py` : `CarevoService.mark_paid` — idempotent on `payment_transactions.gateway_payment_id`, row-locked via `SELECT ... FOR UPDATE` before either idempotency check |
| Amount mismatch handling | BUILT | `CarevoService.mark_paid` — underpaid branch sets `customer_orders.payment_amount_mismatch = true` / `payment_amount_mismatch_at` when `amount_paise < total_paise` |
| Duplicate payment handling | BUILT | `CarevoService.mark_paid` — same `gateway_payment_id` against the same order short-circuits on `order.payment_status == "PAID": return order`; against a different order sets `order._mark_paid_cross_order_ignored = True` and is answered `{"outcome": "IGNORED"}` by `payment_webhook` |
| Refund-due queue | BUILT | Table `customer_orders` columns `refund_required` / `refund_reason` / `refund_flagged_at` (migration `032_refund_and_manual_acceptance.sql`); read by `carevo_admin/controller.py` : `list_refund_due` (`GET /admin/orders/refund-due`); written by `mark_paid`'s terminal-order branch and by `CarevoService.reject_order` |
| Review history | PARTIAL | `order_events` table (`gusto_pos/backend/app/modules/prediction/events.py`, columns `order_id, outlet_id, seq, event_type, occurred_at, actor_type, actor_id, source, payload`) is an append-only operational timeline shared by every order lifecycle event (`PAYMENT_CLAIMED`, `PAYMENT_FAILED`, `PAYMENT_NOT_RECEIVED`, `ORDER_REFUND_MARKED`, etc.). It is NOT a dedicated payment-review/audit table with an outcome/reason/reviewer shape — there is no table a human "confirm/reject with reason" action writes to today. Task 4/7 build on top of this gap. |
| Admin authorization dependency | BUILT | `gusto_pos/backend/app/modules/carevo_admin/deps.py` : `get_current_super_admin` — layers a `SUPER_ADMIN` role check on top of `carevo_customer/deps.py` : `get_current_staff`; applied to every route in `carevo_admin/controller.py` via `Depends(get_current_super_admin)` |
| Existing fee or ledger table | NOT BUILT | No table or column matching `fee`, `commission`, `service_fee`, `platform_fee`, `convenience_fee` anywhere under `gusto_pos/backend/app` (grep, case-insensitive, zero matches). `payment_transactions` and `customer_orders` record what the customer paid the vendor; nothing records money owed BY the vendor TO CareVo. |
| Encryption helper | NOT BUILT | No `cryptography`, `Fernet`, or `AES` match anywhere under `gusto_pos/backend/app` (grep, case-insensitive, zero matches). `gusto_pos/backend/requirements.txt` does not list `cryptography`. No secrets-at-rest helper exists; Task 2 is new work, not a rewrite. |
| Rate limiter | BUILT | In-process, not a library: `app/core/config.py` — `OTP_RATE_LIMIT_PER_HOUR`, `REGISTER_RATE_LIMIT_PER_HOUR`, `LOGIN_RATE_LIMIT_ATTEMPTS` / `LOGIN_RATE_LIMIT_WINDOW_SECONDS`, `PUBLIC_API_RATE_LIMIT_PER_HOUR`; enforced by `CarevoService.check_login_rate_limit`, called from `app/modules/auth/controller.py` (lines 46, 84) per username and per client IP |

## Scope note

Two authority-bearing fields referenced by later tasks have no existing column
anywhere in the schema as of this commit:
- `verification_source` / `verification_status` on any payment row — NO EVIDENCE.
- A vendor-identity concept distinct from `outlets` — NO EVIDENCE. "Vendor" in
  this codebase means `outlets` (one outlet = one restaurant = one biller for
  Task 6/7).

Status: **DONE**
