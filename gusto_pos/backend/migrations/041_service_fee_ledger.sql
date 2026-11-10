-- 041_service_fee_ledger.sql
--
-- Append-only Rs 1 (default) service-fee ledger. CareVo bills the VENDOR
-- this fee per eligible order; CareVo never collects, holds, splits, or
-- settles the CUSTOMER's payment to the vendor -- this table only records
-- what the vendor owes CareVo for the platform, as a hash-chained audit
-- trail. ADDITIVE ONLY, inert until SERVICE_FEE_LEDGER_ENABLED=true.
--
-- ============================================================================
-- BILLABLE EVENT (cite: exact status literals found in this codebase)
-- ============================================================================
-- An order becomes eligible when its status reaches 'PICKED_UP' (migration
-- 023_customer_picked_up.sql) or 'COMPLETED' (both are members of
-- carevo_customer/service.py's _TERMINAL_STATUSES set, line ~89) AND EITHER
--   * customer_orders.payment_status = 'PAID' (the existing CareVo-mediated
--     Cashfree/stub flow), OR
--   * customer_orders.vendor_payment_confirmed_at IS NOT NULL (migration 039
--     -- the vendor's OWN gateway confirmed payment directly to the vendor;
--     Task 5's webhook route is what ever sets this).
--
-- Cancelled, rejected, and expired orders are excluded STRUCTURALLY, not by
-- a separate negative check: carevo_customer/service.py sets status =
-- 'CANCELLED' for both a staff reject (reject_order, line ~3283-3297) and an
-- expired direct-UPI claim (expire_unclaimed_upi_orders, line ~2663), and
-- status = 'ABANDONED' for an unpaid TTL sweep (line ~2540) and a no-show
-- (mark_no_show, line ~5310). An order's status is one value; one that is
-- CANCELLED or ABANDONED cannot simultaneously be PICKED_UP or COMPLETED, so
-- the positive billable-event gate above already excludes every one of
-- these without a second condition. "Refunded" is not a status value in
-- this codebase (see customer_orders.refund_required, migration 032) --
-- a refunded order may still read COMPLETED/PICKED_UP, which is exactly why
-- a charge already written is reversed (entry_type='REVERSAL') rather than
-- prevented: the charge was correct when it was written; the refund is a
-- later fact.
--
-- ============================================================================
-- WHAT THIS DOES
-- ============================================================================
-- 1. CREATE TABLE IF NOT EXISTS service_fee_ledger. UNIQUE(order_id,
--    entry_type) caps one order at exactly one CHARGE and exactly one
--    REVERSAL, ever.
-- 2. A BEFORE INSERT trigger (carevo_fee_ledger_chain) computes prev_hash
--    and entry_hash FOR EVERY ROW -- the application never supplies either.
--    prev_hash is the entry_hash of the most recent row for the SAME
--    outlet_id (NULL for that outlet's first row ever); entry_hash =
--    sha256(prev_hash || '|' || outlet_id || '|' || order_id || '|' ||
--    entry_type || '|' || amount_paise || '|' || created_at), all in a
--    fixed canonical text encoding (see the function body for the exact
--    format string). pg_advisory_xact_lock serializes concurrent inserts
--    for the SAME outlet so two orders completing at once cannot both read
--    the same "latest" row and fork the chain.
-- 3. A BEFORE UPDATE trigger (carevo_fee_ledger_reject_core_mutation)
--    refuses any UPDATE that changes outlet_id, order_id, entry_type,
--    amount_paise, billing_period, prev_hash, entry_hash, or created_at.
--    status and invoice_ref are the only columns it ever allows to change.
--    A BEFORE DELETE / BEFORE TRUNCATE trigger refuses all of both,
--    reusing the existing carevo_reject_mutation() function from migration
--    006 (same append-only pattern, same reasoning: "this deployment
--    connects as the table-owning role, so REVOKE would be a no-op here --
--    a trigger fires for every role and is the reliable choice").
-- 4. fn_advance_fee_entry_status(id, status, invoice_ref) -- the ONE
--    sanctioned way to change status/invoice_ref. Nothing stops a caller
--    writing the UPDATE by hand (the trigger would still allow it, since
--    status/invoice_ref are the allowed columns), but this is the single
--    function app.modules.carevo_payments.fee_ledger calls, which is what
--    "may change only through one function" means at the application layer.
-- 5. verify_chain(outlet_id) -- walks every row for one outlet in
--    created_at order, recomputes each expected entry_hash with the SAME
--    canonical formula the insert trigger used, and returns the id of the
--    FIRST row whose stored hash (or stored prev_hash) does not match, or
--    no rows at all when the chain is intact ("OK").
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- See docs/ops/041_service_fee_ledger_rollback.sql.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS service_fee_ledger (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outlet_id      uuid        NOT NULL REFERENCES outlets(id),
    order_id       uuid        NOT NULL REFERENCES customer_orders(id),
    entry_type     varchar(10) NOT NULL
                       CHECK (entry_type IN ('CHARGE', 'REVERSAL')),
    amount_paise   integer     NOT NULL CHECK (amount_paise > 0),
    billing_period varchar(7)  NOT NULL,   -- 'YYYY-MM', IST calendar month
    status         varchar(10) NOT NULL DEFAULT 'OPEN'
                       CHECK (status IN ('OPEN', 'INVOICED', 'PAID')),
    invoice_ref    varchar(100) NULL,
    prev_hash      varchar(64) NULL,
    entry_hash     varchar(64) NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT uq_service_fee_ledger_order_entry_type UNIQUE (order_id, entry_type)
);

CREATE INDEX IF NOT EXISTS ix_service_fee_ledger_outlet_created
    ON service_fee_ledger (outlet_id, created_at);
CREATE INDEX IF NOT EXISTS ix_service_fee_ledger_billing_period
    ON service_fee_ledger (outlet_id, billing_period);

COMMENT ON TABLE service_fee_ledger IS
    'Append-only ledger of the platform service fee CareVo bills a VENDOR '
    'per eligible order. Hash-chained per outlet (prev_hash/entry_hash, '
    'computed by a trigger -- the application never supplies either). '
    'CareVo never collects, holds, or settles the underlying customer '
    'payment; this records only what the vendor owes the platform.';

-- ---------------------------------------------------------------------------
-- Chain-building trigger: fills prev_hash + entry_hash on every INSERT.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION carevo_fee_ledger_chain() RETURNS trigger AS $$
DECLARE
  v_prev_hash varchar(64);
  v_canonical text;
BEGIN
  -- Serializes concurrent inserts for the SAME outlet: the lock is held for
  -- the rest of this transaction, so a second concurrent insert for this
  -- outlet blocks here until the first commits (or rolls back) rather than
  -- both reading the same "latest" row and forking the chain.
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.outlet_id::text, 0));

  SELECT entry_hash INTO v_prev_hash
    FROM service_fee_ledger
   WHERE outlet_id = NEW.outlet_id
   ORDER BY created_at DESC, id DESC
   LIMIT 1;

  NEW.prev_hash := v_prev_hash;   -- NULL for this outlet's first-ever row

  IF NEW.created_at IS NULL THEN
    NEW.created_at := now();
  END IF;

  -- FIXED canonical encoding: '|'-joined fields, prev_hash as the empty
  -- string when NULL (so the first row in a chain has a reproducible,
  -- non-NULL-concatenation hash input), created_at as microsecond-precision
  -- UTC ISO-8601. verify_chain() below MUST reproduce this exactly.
  v_canonical := coalesce(v_prev_hash, '') || '|' ||
                 NEW.outlet_id::text || '|' ||
                 NEW.order_id::text || '|' ||
                 NEW.entry_type || '|' ||
                 NEW.amount_paise::text || '|' ||
                 to_char(NEW.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');

  NEW.entry_hash := encode(digest(v_canonical, 'sha256'), 'hex');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER service_fee_ledger_chain
  BEFORE INSERT ON service_fee_ledger
  FOR EACH ROW EXECUTE FUNCTION carevo_fee_ledger_chain();

-- ---------------------------------------------------------------------------
-- Immutability: UPDATE may only touch status/invoice_ref. DELETE/TRUNCATE
-- are refused outright, reusing migration 006's carevo_reject_mutation().
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION carevo_fee_ledger_reject_core_mutation() RETURNS trigger AS $$
BEGIN
  IF NEW.outlet_id      IS DISTINCT FROM OLD.outlet_id
     OR NEW.order_id      IS DISTINCT FROM OLD.order_id
     OR NEW.entry_type    IS DISTINCT FROM OLD.entry_type
     OR NEW.amount_paise  IS DISTINCT FROM OLD.amount_paise
     OR NEW.billing_period IS DISTINCT FROM OLD.billing_period
     OR NEW.prev_hash     IS DISTINCT FROM OLD.prev_hash
     OR NEW.entry_hash    IS DISTINCT FROM OLD.entry_hash
     OR NEW.created_at    IS DISTINCT FROM OLD.created_at
  THEN
    RAISE EXCEPTION
      'service_fee_ledger row % is immutable except status/invoice_ref',
      OLD.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER service_fee_ledger_core_immutable
  BEFORE UPDATE ON service_fee_ledger
  FOR EACH ROW EXECUTE FUNCTION carevo_fee_ledger_reject_core_mutation();

CREATE OR REPLACE TRIGGER service_fee_ledger_no_delete
  BEFORE DELETE ON service_fee_ledger
  FOR EACH ROW EXECUTE FUNCTION carevo_reject_mutation();
CREATE OR REPLACE TRIGGER service_fee_ledger_no_truncate
  BEFORE TRUNCATE ON service_fee_ledger
  FOR EACH STATEMENT EXECUTE FUNCTION carevo_reject_mutation();

-- ---------------------------------------------------------------------------
-- The ONE sanctioned function for a status/invoice_ref change.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_advance_fee_entry_status(
    p_id uuid, p_status varchar, p_invoice_ref varchar DEFAULT NULL
) RETURNS void AS $$
BEGIN
  UPDATE service_fee_ledger
     SET status = p_status,
         invoice_ref = coalesce(p_invoice_ref, invoice_ref)
   WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------
-- verify_chain(outlet_id): first broken row, or no rows ("OK").
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION verify_chain(p_outlet_id uuid)
RETURNS TABLE (broken_id uuid, reason text) AS $$
DECLARE
  r record;
  v_expected_prev varchar(64) := NULL;
  v_expected_hash varchar(64);
  v_canonical text;
BEGIN
  FOR r IN
    SELECT id, order_id, entry_type, amount_paise, prev_hash, entry_hash, created_at
      FROM service_fee_ledger
     WHERE outlet_id = p_outlet_id
     ORDER BY created_at ASC, id ASC
  LOOP
    IF r.prev_hash IS DISTINCT FROM v_expected_prev THEN
      broken_id := r.id;
      reason := 'prev_hash does not match the preceding row in this outlet''s chain';
      RETURN NEXT;
      RETURN;
    END IF;

    v_canonical := coalesce(v_expected_prev, '') || '|' ||
                   p_outlet_id::text || '|' ||
                   r.order_id::text || '|' ||
                   r.entry_type || '|' ||
                   r.amount_paise::text || '|' ||
                   to_char(r.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
    v_expected_hash := encode(digest(v_canonical, 'sha256'), 'hex');

    IF r.entry_hash IS DISTINCT FROM v_expected_hash THEN
      broken_id := r.id;
      reason := 'entry_hash does not match the recomputed hash for this row';
      RETURN NEXT;
      RETURN;
    END IF;

    v_expected_prev := r.entry_hash;
  END LOOP;
  -- No rows returned at all = the chain is intact ("OK" is the ABSENCE of
  -- a broken row, checked by the caller via row count, not a sentinel
  -- value here -- there is no outlet_id for which an all-NULL row would be
  -- meaningful).
  RETURN;
END;
$$ LANGUAGE plpgsql;
