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
`https://razorpay.com/docs/webhooks/validate-test/`, fetched during this
task (WebFetch).

**VERIFIED against that page:**
- Header name: `X-Razorpay-Signature`.
- What is signed: the raw webhook request body — the docs explicitly warn
  against parsing or casting the body before verification.
- Algorithm and encoding: HMAC-SHA256, hex digest (`expected_signature =
  hmac('sha256', message, key)`).
- This adapter's `verify()` matches all three exactly: `hmac.new(secret,
  raw_body, hashlib.sha256).hexdigest()`, compared with
  `hmac.compare_digest`.

**UNVERIFIED / not part of Razorpay's documented contract:**
- A timestamp field used for webhook replay protection. The docs describe
  `x-razorpay-event-id` for duplicate-event detection, not a timestamp for
  signature-replay tolerance.
- This codebase's `ProviderAdapter` framework requires a timestamp check on
  every adapter (same pattern as the existing `CASHFREE_WEBHOOK_MAX_AGE_S`
  check). `RazorpayWebhookAdapter` satisfies that framework requirement by
  reading a header, `X-Razorpay-Event-Timestamp`, that is **not** part of
  Razorpay's documented webhook contract — real Razorpay webhooks do not
  send it. A genuine Razorpay delivery would therefore always fail this
  adapter's `MissingTimestampError` check today.

This gap, not just caution, is why the adapter ships with
`production_eligible = False` and behind `RAZORPAY_ADAPTER_ENABLED` (default
`false`): it is usable against test fixtures that supply the header, and
NOT usable against real Razorpay traffic without first resolving where a
trustworthy event timestamp comes from (most likely: derive it from the
payload's own `created_at` field, read only AFTER the signature over the
raw body has already verified — not attempted here, out of scope for this
task).

## Status table

| Provider | Header | Algorithm | Doc source | Verified | production_eligible |
|---|---|---|---|---|---|
| Cashfree | `x-webhook-signature` + `x-webhook-timestamp` | base64(HMAC-SHA256(timestamp+body)) | this repo's existing, shipped code | YES (pre-existing) | True |
| Razorpay | `X-Razorpay-Signature` | hex(HMAC-SHA256(body)) | https://razorpay.com/docs/webhooks/validate-test/ | YES for signature scheme; NO for timestamp/replay (not in Razorpay's docs — our own addition) | False |
