-- Migration 017: staff push tokens + staff-addressable notification log
--
-- Additive and idempotent throughout. Re-running is a no-op.
--
-- WHAT NEEDS NO DDL AT ALL --------------------------------------------------
-- The two new event types (ORDER_REJECTED, PAYMENT_FAILED) and the CANCELLED
-- order status require NOTHING here. Verified against prod:
--   * order_events.event_type has no CHECK constraint  -> new types just work
--   * customer_orders.status   has no CHECK constraint -> CANCELLED just works
-- The event vocabulary lives in app/modules/prediction/events.py and is a CODE
-- change only. Inventing a CHECK now would be a new restriction on live tables,
-- not a fix — and would have to enumerate every historical value correctly to
-- avoid rejecting rows that already exist.
--
-- CANCELLED is already treated as terminal by existing queries
-- (`status NOT IN ('COMPLETED','CANCELLED','ABANDONED')` in the TTL sweeper and
-- the active-order feed), so wiring it up changes no filter.
--
-- WHAT THIS MIGRATION IS ACTUALLY FOR ----------------------------------------
-- Pushing to STAFF. Migration 014 built the push stack customer-only:
-- customers.fcm_token, and push_notifications.customer_id NOT NULL REFERENCES
-- customers(id). There is no column anywhere that can hold a staff device
-- token, and the notification log physically cannot record a staff send.
-- "Notify the outlet on every paid order" is impossible without this.

-- 1. Staff device token --------------------------------------------------------
-- Mirrors exactly what migration 014 added to customers, deliberately: same
-- column names, same types, same nullability, so the send path can treat a
-- staff row and a customer row identically.
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS fcm_token varchar(255);

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS fcm_token_updated_at timestamptz;

-- One outlet can have several staff logins, and a paid order must reach all of
-- their devices. Partial: the overwhelming majority of rows have no token.
CREATE INDEX IF NOT EXISTS idx_users_outlet_fcm
    ON users (outlet_id)
    WHERE fcm_token IS NOT NULL;

-- 2. Let the notification log address staff too --------------------------------
-- customer_id must become nullable, because a staff notification has no
-- customer. This is the one non-additive change in the file: it RELAXES a
-- constraint, so every existing row stays valid and every existing INSERT
-- (which always supplies customer_id) keeps working unchanged.
ALTER TABLE push_notifications
    ALTER COLUMN customer_id DROP NOT NULL;

ALTER TABLE push_notifications
    ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id) ON DELETE CASCADE;

-- Exactly one recipient, never both, never neither. Without this the nullable
-- customer_id above would silently permit orphan rows addressed to nobody.
-- Added NOT VALID then VALIDATEd separately so the ACCESS EXCLUSIVE lock is
-- held only briefly — the existing rows all satisfy it, but on a live table
-- the two-step is the safe habit.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'push_notifications_one_recipient'
    ) THEN
        ALTER TABLE push_notifications
            ADD CONSTRAINT push_notifications_one_recipient
            CHECK (num_nonnulls(customer_id, user_id) = 1) NOT VALID;
        ALTER TABLE push_notifications VALIDATE CONSTRAINT push_notifications_one_recipient;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_push_user_kind
    ON push_notifications (user_id, kind, created_at DESC)
    WHERE user_id IS NOT NULL;
