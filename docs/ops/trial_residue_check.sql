-- ============================================================================
-- YOUPI trial residue check — READ-ONLY
--
-- Purpose: run against a COPY of production (never prod itself) to find every
-- customer_orders / payment_transactions row left behind by the YOUPI PG
-- trial (branch origin/youpi-trial), before that branch is cut over or
-- discarded. Every statement below is a SELECT. Nothing here writes,
-- deletes, or alters anything.
--
-- Markers, determined by reading origin/youpi-trial read-only
-- (`git show origin/youpi-trial:<path>`) — no checkout, no merge, no local
-- modification of that branch:
--
--   1. gateway name
--      payment_transactions.gateway = 'youpi'
--      (gusto_pos/backend/app/modules/carevo_payments/gateway.py:
--       `class YoupiGateway(PaymentGateway): name = "youpi"`; every row this
--       code inserts via PaymentTransaction(gateway=g_order.gateway, ...) in
--       carevo_customer/service.py carries that literal.)
--
--   2. id prefix
--      payment_transactions.gateway_payment_id LIKE 'youpi\_%'
--      (gateway.py: `def make_payment_id(self): return _rand("youpi")`, and
--       `_rand(prefix) -> f"{prefix}_{secrets.token_hex(12)}"`. service.py:
--       `pay_id = gateway_payment_id or gw.make_payment_id()` — this prefix
--       appears ONLY when the real webhook supplied no id and the code
--       generated one itself (e.g. the CREATED row before a webhook lands,
--       or a transaction that never reached PAID). A row that DID complete
--       via a real webhook carries YOUPI's own bank UTR in this column
--       instead (see parse_webhook: gateway_payment_id = payload["utr"]),
--       which has no predictable prefix — marker (1) is what catches those,
--       not this one. Treat this LIKE pattern as a strict subset, not the
--       full set.)
--
--   3. trial amount
--      payment_transactions.amount = 1.00  (and customer_orders.total_amount)
--      (YOUPI_INTEGRATION.md, as of 7f17b97e: "An un-overridden build sends
--       trial traffic — including real ₹1 payments — to production." The
--       trial was deliberately run at the smallest payable amount Cashfree/
--       YOUPI will accept, specifically so a leaked real charge costs ₹1.)
--
--   4. test/trial outlet
--      ** NOT present anywhere in origin/youpi-trial's code or migrations. **
--      No outlet id, name, or flag in gateway.py, service.py, or any
--      migration marks an outlet as "the trial outlet" — the trial ran
--      against whichever outlet the owner pointed the trial Render service
--      at, which is an operational fact, not a code fact. The placeholder
--      below MUST be filled in with the real outlet id/name before this
--      query is run for real — do not run it with the placeholder as-is.
--
-- Scope: only customer_orders + payment_transactions. The YOUPI flow (create
-- order / webhook) never touches the legacy POS `orders` table — confirmed
-- by reading carevo_customer/service.py's create-order path, which inserts
-- into PaymentTransaction keyed on customer_order_id only.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- Marker 1: gateway = 'youpi'
-- ----------------------------------------------------------------------------
SELECT
    pt.id              AS payment_transaction_id,
    pt.customer_order_id,
    pt.gateway,
    pt.gateway_order_id,
    pt.gateway_payment_id,
    pt.amount,
    pt.currency,
    pt.status,
    pt.created_at,
    co.outlet_id,
    co.status           AS order_status,
    co.payment_status,
    co.total_amount
FROM payment_transactions pt
JOIN customer_orders co ON co.id = pt.customer_order_id
WHERE pt.gateway = 'youpi'
ORDER BY pt.created_at DESC;


-- ----------------------------------------------------------------------------
-- Marker 2: id prefix 'youpi_' on gateway_payment_id
-- (subset of marker 1 in practice, kept separate so it survives on its own
-- if the `gateway` column were ever blank or miscategorised)
-- ----------------------------------------------------------------------------
SELECT
    pt.id              AS payment_transaction_id,
    pt.customer_order_id,
    pt.gateway,
    pt.gateway_payment_id,
    pt.amount,
    pt.status,
    pt.created_at,
    co.outlet_id
FROM payment_transactions pt
JOIN customer_orders co ON co.id = pt.customer_order_id
WHERE pt.gateway_payment_id LIKE 'youpi\_%'
ORDER BY pt.created_at DESC;


-- ----------------------------------------------------------------------------
-- Marker 3: ₹1 trial amount
-- Checked on BOTH tables: total_amount on the order header, amount on the
-- transaction row — a failed/abandoned trial order can have one without the
-- other (e.g. a CREATED transaction before the order total is finalised).
-- ----------------------------------------------------------------------------
SELECT
    co.id              AS customer_order_id,
    co.outlet_id,
    co.status,
    co.payment_status,
    co.total_amount,
    co.created_at
FROM customer_orders co
WHERE co.total_amount = 1.00
ORDER BY co.created_at DESC;

SELECT
    pt.id              AS payment_transaction_id,
    pt.customer_order_id,
    pt.gateway,
    pt.amount,
    pt.status,
    pt.created_at
FROM payment_transactions pt
WHERE pt.amount = 1.00
ORDER BY pt.created_at DESC;


-- ----------------------------------------------------------------------------
-- Marker 4: test/trial outlet
--
-- *** FILL IN THE REAL OUTLET BEFORE RUNNING. ***
-- No such marker exists in code (see note above) — this is a best-effort
-- pattern match on outlet name, included only so the owner has a starting
-- point to confirm or correct in the review step below. Replace the
-- '%trial%'/'%test%'/'%youpi%'/'%demo%' pattern and/or the outlet id with the
-- actual outlet(s) the trial Render service pointed at.
-- ----------------------------------------------------------------------------
SELECT
    o.id               AS outlet_id,
    o.name             AS outlet_name,
    co.id              AS customer_order_id,
    co.status,
    co.payment_status,
    co.total_amount,
    co.created_at
FROM customer_orders co
JOIN outlets o ON o.id = co.outlet_id
WHERE o.name ILIKE ANY (ARRAY['%trial%', '%test%', '%youpi%', '%demo%'])
   -- OR o.id = '<PASTE REAL TRIAL OUTLET UUID HERE>'
ORDER BY co.created_at DESC;


-- ----------------------------------------------------------------------------
-- Count summary — one row per marker, so the review step below has a single
-- number to start from instead of re-reading four result sets.
-- ----------------------------------------------------------------------------
SELECT 'gateway = youpi'              AS marker,
       count(*)                       AS payment_transactions_rows
FROM payment_transactions WHERE gateway = 'youpi'
UNION ALL
SELECT 'gateway_payment_id LIKE youpi_%',
       count(*)
FROM payment_transactions WHERE gateway_payment_id LIKE 'youpi\_%'
UNION ALL
SELECT 'payment_transactions.amount = 1.00',
       count(*)
FROM payment_transactions WHERE amount = 1.00
UNION ALL
SELECT 'customer_orders.total_amount = 1.00',
       count(*)
FROM customer_orders WHERE total_amount = 1.00
UNION ALL
SELECT 'outlet name matches trial/test/youpi/demo pattern',
       count(*)
FROM customer_orders co
JOIN outlets o ON o.id = co.outlet_id
WHERE o.name ILIKE ANY (ARRAY['%trial%', '%test%', '%youpi%', '%demo%']);


-- ============================================================================
-- RUNBOOK — before cutover
--
-- 1. Run the four marker queries above against a COPY of production (never
--    prod itself), after first replacing the outlet placeholder in Marker 4
--    with the real trial outlet id(s) confirmed with the owner.
-- 2. Review every returned row with the owner, outlet by outlet: for each
--    row, decide KEEP (it is a genuine order/payment that should survive the
--    cutover) or ARCHIVE (it was trial residue — a YOUPI test payment or
--    order that must not appear in production reporting).
-- 3. Record that decision per row (or per batch, if the owner groups them)
--    before any DELETE/UPDATE is written — this script intentionally
--    contains no such statement. A follow-up script, written only after this
--    review is signed off, is where the archive/delete action belongs.
-- 4. Re-run the count summary after the owner's decision is implemented and
--    confirm it reflects the agreed outcome (zero remaining residue, or the
--    exact count the owner chose to keep).
-- ============================================================================
