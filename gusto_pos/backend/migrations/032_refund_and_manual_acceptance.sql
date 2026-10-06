-- 032_refund_and_manual_acceptance.sql
--
-- Two features, one migration, because they share a trigger: an order the
-- restaurant never accepted is an order whose money has to come back.
--
--   (a) a REFUND-DUE flag on customer_orders, so "we owe this customer money"
--       is a queryable fact rather than something reconstructed from events;
--   (b) per-outlet MANUAL ACCEPTANCE — the restaurant must tap Accept within a
--       timeout or the order expires and the customer is refunded.
--
-- ADDITIVE ONLY. Eleven new columns across two tables, two partial indexes.
-- No existing column is altered or dropped, no row is read or written.
--
-- ============================================================================
-- WHY NEW COLUMNS AND NOT NEW STATUS VALUES
-- ============================================================================
-- The obvious shape for (b) is a status like 'AWAITING_ACCEPTANCE' in
-- customer_orders.status. That was rejected deliberately.
--
-- `status` is read in a great many places that enumerate it as a closed set,
-- and several of those sets are security- or money-relevant:
--
--   _LIVE_STATUSES      = {PAID, RECEIVED, PREPARING, READY}   -- TTL sweeper
--   _TERMINAL_STATUSES  = {CANCELLED, COMPLETED, ABANDONED, PICKED_UP}
--   REJECTABLE_STATUSES                                        -- reject gate
--   _PROGRESSION                                               -- advance_status
--
-- A twelfth status value would have to be added to each of them correctly, and
-- the failure mode of missing one is silent: an order invisible to the TTL
-- sweeper never expires, or an order that mark_paid believes is non-terminal
-- can be resurrected by a replayed webhook. `acceptance_state` is a SEPARATE
-- axis, NULL for every order that is not in a manual-acceptance flow, so every
-- one of those existing sets keeps its exact current meaning.
--
-- An order awaiting acceptance therefore has status='PAID' — which is true, it
-- is paid — plus acceptance_state='AWAITING'.
--
-- ============================================================================
-- customer_orders.refund_required / refund_reason / refund_flagged_at
-- ============================================================================
-- FALSE for every existing row, which is correct: nothing in the system has
-- ever owed a refund it recorded. Set by exactly three paths, all of which
-- take money and then fail to deliver food:
--
--   reject_order           — staff refuse a PAID order
--   _expire_stale_pickups  — the 45-minute TTL abandons a PAID-or-later order
--   acceptance expiry      — nobody tapped Accept in time
--
-- NOTE on the TTL path: _LIVE_STATUSES includes PAID/RECEIVED/PREPARING/READY,
-- so the sweeper already abandons PAID orders. The code comment beside
-- ORDER_ABANDONED describes it as expiring "an order nobody paid for", which
-- is not what the predicate does. This flag is what makes that discrepancy
-- visible and actionable rather than silent.
--
-- NOT a refund ledger and NOT a gateway integration. There is no code anywhere
-- in this repository that calls a Cashfree refund API, and this migration does
-- not add one. The flag means "a human owes this customer money"; settling it
-- is still manual and off-app, and marking it done is an explicit admin action.
--
-- ============================================================================
-- customer_orders.acceptance_state + the five columns around it
-- ============================================================================
-- NULL = this order is not in a manual-acceptance flow, which is every order
-- at every outlet until someone sets outlets.acceptance_mode='manual'. That is
-- the property that makes this migration inert on deploy and keeps the whole
-- existing auto path byte-identical.
--
--   AWAITING  — paid, restaurant has been alerted, clock running
--   ACCEPTED  — a human tapped Accept (accepted_at + prep_minutes_committed)
--   REJECTED  — a human tapped Reject
--   EXPIRED   — the deadline passed with no tap
--
-- alert_count / last_alert_at drive the re-push ladder (up to 3 alerts, 30s
-- apart) and are what an acknowledgement stops. They live on the order rather
-- than in memory because the alert has to survive a redeploy — Render restarts
-- freely and an in-process counter would reset the ladder to zero.
--
-- ============================================================================
-- outlets.acceptance_mode / acceptance_timeout_s / consecutive_expiries
-- ============================================================================
-- DEFAULT 'auto' is the switch that makes this whole feature opt-in per outlet.
-- Every existing outlet gets 'auto' and behaves exactly as it does today.
--
-- consecutive_expiries counts expiries in a row for one outlet and is reset by
-- any accept or reject. At 3 the outlet is auto-closed via the EXISTING
-- is_manually_closed column (migration 024) rather than a new one — a
-- restaurant that is not answering is closed, and that is already a concept
-- with a single meaning and one set of consumers.
--
-- 180s default timeout: long enough that a counter mid-rush is not punished,
-- short enough that a customer is not left waiting on a dead outlet.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- Purely additive, so rollback is clean at any time and loses only the new
-- data:
--
--   DROP INDEX IF EXISTS customer_orders_refund_due_idx;
--   DROP INDEX IF EXISTS customer_orders_awaiting_acceptance_idx;
--   ALTER TABLE customer_orders
--       DROP COLUMN refund_required, DROP COLUMN refund_reason,
--       DROP COLUMN refund_flagged_at, DROP COLUMN acceptance_state,
--       DROP COLUMN acceptance_deadline_at, DROP COLUMN accepted_at,
--       DROP COLUMN prep_minutes_committed, DROP COLUMN alert_count,
--       DROP COLUMN last_alert_at;
--   ALTER TABLE outlets
--       DROP COLUMN acceptance_mode, DROP COLUMN acceptance_timeout_s,
--       DROP COLUMN consecutive_expiries;
--
-- It stops being clean once a real refund has been flagged and settled, since
-- refund_reason/refund_flagged_at are then the only record that it happened.

ALTER TABLE customer_orders
    ADD COLUMN IF NOT EXISTS refund_required        boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS refund_reason          text        NULL,
    ADD COLUMN IF NOT EXISTS refund_flagged_at      timestamptz NULL,
    ADD COLUMN IF NOT EXISTS acceptance_state       text        NULL,
    ADD COLUMN IF NOT EXISTS acceptance_deadline_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS accepted_at            timestamptz NULL,
    ADD COLUMN IF NOT EXISTS prep_minutes_committed integer     NULL,
    ADD COLUMN IF NOT EXISTS alert_count            integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_alert_at          timestamptz NULL;

-- CHECK constraints are added separately and guarded, because ADD CONSTRAINT
-- has no IF NOT EXISTS in PostgreSQL and this file must stay idempotent.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_acceptance_state'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_acceptance_state
            CHECK (acceptance_state IS NULL OR acceptance_state IN
                   ('AWAITING', 'ACCEPTED', 'REJECTED', 'EXPIRED'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_customer_orders_prep_minutes'
    ) THEN
        ALTER TABLE customer_orders
            ADD CONSTRAINT ck_customer_orders_prep_minutes
            CHECK (prep_minutes_committed IS NULL OR prep_minutes_committed > 0);
    END IF;
END $$;

ALTER TABLE outlets
    ADD COLUMN IF NOT EXISTS acceptance_mode      text    NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS acceptance_timeout_s integer NOT NULL DEFAULT 180,
    ADD COLUMN IF NOT EXISTS consecutive_expiries integer NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_acceptance_mode'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_acceptance_mode
            CHECK (acceptance_mode IN ('auto', 'manual'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_outlets_acceptance_timeout'
    ) THEN
        ALTER TABLE outlets
            ADD CONSTRAINT ck_outlets_acceptance_timeout
            CHECK (acceptance_timeout_s BETWEEN 30 AND 1800);
    END IF;
END $$;

-- The refund queue. Partial, because the flagged set is tiny next to the table
-- and this index exists only to serve the admin "who are we paying back" view.
CREATE INDEX IF NOT EXISTS customer_orders_refund_due_idx
    ON customer_orders (refund_flagged_at)
    WHERE refund_required;

-- The deadline sweeper's working set: orders still waiting on a human. Also
-- partial — AWAITING is a transient state holding at most a handful of rows per
-- outlet, so a full index would be almost entirely dead weight.
CREATE INDEX IF NOT EXISTS customer_orders_awaiting_acceptance_idx
    ON customer_orders (acceptance_deadline_at)
    WHERE acceptance_state = 'AWAITING';

COMMENT ON COLUMN customer_orders.refund_required IS
    'A human owes this customer money: the order was paid and then rejected, '
    'TTL-abandoned or acceptance-expired. NOT a gateway refund — no code in '
    'this repo calls a Cashfree refund API. Cleared only by an explicit admin '
    'mark-done, which writes ORDER_REFUND_MARKED with the actor.';

COMMENT ON COLUMN customer_orders.acceptance_state IS
    'NULL = not in a manual-acceptance flow (every order at an auto outlet, '
    'which is the default). AWAITING | ACCEPTED | REJECTED | EXPIRED. A '
    'SEPARATE axis from status deliberately: status is enumerated as a closed '
    'set in the TTL sweeper, the terminal-status guard, the reject gate and '
    'advance_status, and adding a value to it risks silently missing one.';

COMMENT ON COLUMN customer_orders.acceptance_deadline_at IS
    'now() + outlets.acceptance_timeout_s, stamped when the order enters '
    'AWAITING. For a SCHEDULED (held) order the clock starts at RELEASE, not '
    'at payment — otherwise a pickup three hours out would expire immediately.';

COMMENT ON COLUMN customer_orders.alert_count IS
    'Alerts pushed for this order (max 3, 30s apart). Persisted rather than '
    'held in memory so the ladder survives a redeploy; Render restarts freely '
    'and an in-process counter would silently restart the ladder.';

COMMENT ON COLUMN customer_orders.prep_minutes_committed IS
    'What the restaurant promised when it tapped Accept. The customer-facing '
    'ETA is still the prediction engine''s; this is the human''s own estimate, '
    'recorded for later comparison against order_outcome.';

COMMENT ON COLUMN outlets.acceptance_mode IS
    '''auto'' (default, and today''s behaviour exactly: a paid order is '
    'accepted automatically) or ''manual'' (staff must tap Accept within '
    'acceptance_timeout_s or the order expires and a refund is flagged).';

COMMENT ON COLUMN outlets.consecutive_expiries IS
    'Acceptance expiries in a row for this outlet; reset to 0 by any accept or '
    'reject. At 3 the outlet is auto-closed by setting the EXISTING '
    'is_manually_closed (migration 024) rather than adding a second '
    '"closed" concept.';
