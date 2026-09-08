-- Migration 018: extend push_notifications.kind for staff-addressed pushes
--
-- Fixes an omission in 017. That migration added the COLUMNS staff push needs
-- but missed the pre-existing push_kind_valid CHECK, which enumerates kinds and
-- therefore rejects every new one.
--
-- Why this mattered more than a missing log row: the log INSERT in
-- PushService.send / send_staff is best-effort (wrapped in try/except), so the
-- rejection was SILENT. The push would transmit and simply never be recorded.
-- notify_outlet_new_order reads that same table for its idempotency guard, so
-- with no rows ever written, every webhook retry would re-buzz every staff
-- device at the outlet instead of being suppressed.
--
-- Idempotent: DROP IF EXISTS then recreate with the widened list. Every
-- existing row satisfies the new list (it is a strict superset), and the table
-- is tiny, so the ACCESS EXCLUSIVE lock is momentary.

ALTER TABLE push_notifications
    DROP CONSTRAINT IF EXISTS push_kind_valid;

ALTER TABLE push_notifications
    ADD CONSTRAINT push_kind_valid CHECK (kind IN (
        -- existing, unchanged
        'ORDER_STATUS',
        'REENGAGEMENT',
        'DISH_SUGGESTION',
        -- staff-addressed (017): one per paid order, to every device at the
        -- outlet. This is what gives staff the chance to reject a wrong order,
        -- since there is no Accept gate holding it up.
        'STAFF_NEW_ORDER',
        -- customer-addressed: one per item marked N/A, named individually so
        -- the customer learns WHICH dish is off, not just how many.
        'ITEM_UNAVAILABLE'
    ));
