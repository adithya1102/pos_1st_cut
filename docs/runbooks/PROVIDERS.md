# Provider adapter verification status

`gusto_pos/backend/app/modules/carevo_payments/adapters.py` — `ProviderAdapter`
implementations and what each one's signature scheme was checked against.

## Cashfree — `CashfreeAdapter`

**Source of verification:** this repository's own, already-shipped
`CashfreeGateway.verify_webhook_signature` /
`CashfreeGateway.parse_webhook` (`gusto_pos/backend/app/modules/carevo_payments/gateway.py`).
`CashfreeAdapter` calls these two methods directly rather than
reimplementing the scheme, so there is nothing new to verify beyond "does
the call site match the existing one" — it does (same raw bytes, same
`signature`/`timestamp` arguments, same order, as
`carevo_customer/controller.py`'s `payment_webhook`).

`production_eligible = True`.

## Razorpay — `RazorpayWebhookAdapter`

**Source of verification:** Razorpay's official documentation,
`https://razorpay.com/docs/webhooks/validate-test/`, fetched via WebFetch
twice -- once for the original Task 3 adapter, once again for this fix
pass (reconcile review Task 7) -- plus two further WebFetch attempts
(`https://razorpay.com/docs/webhooks/payloads/` and
`https://razorpay.com/docs/webhooks/`) made specifically to check the
payload envelope's `created_at` field (see below).

**VERIFIED against the validate-test page (both fetches agreed):**
- Header name: `X-Razorpay-Signature`.
- What is signed: the raw webhook request body — the docs explicitly warn
  against parsing or casting the body before verification.
- Algorithm and encoding: HMAC-SHA256, hex digest (`expected_signature =
  hmac('sha256', message, key)`).
- Idempotency: `x-razorpay-event-id` — quoted directly from the docs,
  "You can identify the duplicate webhooks using the `x-razorpay-event-id`
  header. The value for this header is unique per event."
- This adapter's `verify()` matches all four: `hmac.new(secret, raw_body,
  hashlib.sha256).hexdigest()` compared with `hmac.compare_digest`;
  `event_id = h.get("x-razorpay-event-id")` (falling back to
  `"body:" + sha256(raw_body)` only when that header is absent, the same
  fallback `reconciliation.apply_vendor_payment_event` uses for a Cashfree
  delivery with no payment id).
- The documentation does **not** describe any timestamp header or field
  used for signature-replay protection. **FIXED (this task):** the
  adapter previously required a header, `X-Razorpay-Event-Timestamp`, that
  real Razorpay deliveries never send — every genuine delivery failed
  `MissingTimestampError`. That requirement is now removed entirely.
  Replay defence is `payment_events`' own
  `UNIQUE(provider, event_id)` dedup, which does not depend on any
  provider-specific header.

**UNVERIFIED** (reflects an actual gap in what WebFetch could confirm, not
a guess papered over): whether the Razorpay webhook JSON envelope (the
top-level object, sibling to `event`/`payload`, NOT the nested
`payload.payment.entity`) carries a `created_at` timestamp field. The
`validate-test` page does not show a sample payload; a follow-up WebFetch
of `https://razorpay.com/docs/webhooks/payloads/` returned "no information
is given about the webhook JSON payload envelope structure"; a WebFetch of
`https://razorpay.com/docs/webhooks/` likewise found no sample JSON on
that page; a fourth attempt at
`https://razorpay.com/docs/payments/payment-gateway/webhooks/` 404'd.
**Consequently the adapter treats this field as optional and best-effort
only:** `payload.get("created_at")`, checked against the generous
`CASHFREE_WEBHOOK_MAX_AGE_S` window ONLY when it is present and numeric;
a missing or non-numeric value never causes a rejection. This satisfies
the reconcile-fix-pass requirement ("check it against a generous window
and reject only when it is present and out of window") without claiming
documentation this task could not actually confirm.

**`production_eligible` is now `True`** (was `False`): the only
documented gap — the fabricated timestamp-header requirement — is fixed.
The adapter is still gated behind `RAZORPAY_ADAPTER_ENABLED` (default
`false`), which is a deployment decision, not a correctness one.

## Status table

| Provider | Header | Algorithm | Doc source | Verified | production_eligible |
|---|---|---|---|---|---|
| Cashfree | `x-webhook-signature` + `x-webhook-timestamp` | base64(HMAC-SHA256(timestamp+body)) | this repo's existing, shipped code | YES (pre-existing) | True |
| Razorpay | `X-Razorpay-Signature` | hex(HMAC-SHA256(body)) | https://razorpay.com/docs/webhooks/validate-test/ | YES for signature + event-id; the old timestamp-header requirement (never in Razorpay's docs) is removed; optional `created_at` window check is UNVERIFIED against Razorpay's docs (best-effort, never rejects for absence) | True |
