-- 028_auto_advance_schedule.sql
--
-- Durable schedule for roster-scoped auto-progression (testing only). Each row
-- is ONE order's next pending stage and when it is due. A background poller
-- advances rows whose due_at has passed, then rewrites the row to the following
-- stage (or deletes it after READY, whose auto-pickup closes the order).
--
-- WHY A TABLE (not in-memory asyncio tasks): persisting the next step makes
-- progression survive a backend restart / redeploy. On boot the poller finds
-- any past-due row and resumes it — no manual re-pay or tap. This replaces the
-- previous in-memory scheduling, which lost all pending steps on restart.
--
-- One row per order (order_id PRIMARY KEY): re-paying / re-scheduling upserts.
-- ON DELETE CASCADE so a removed order can never leave an orphan schedule row.
--
-- Additive, idempotent, reversible: DROP TABLE auto_advance_schedule;
-- Touches no existing table (only references customer_orders).

CREATE TABLE IF NOT EXISTS auto_advance_schedule (
    order_id   uuid        PRIMARY KEY REFERENCES customer_orders(id) ON DELETE CASCADE,
    next_stage varchar(20) NOT NULL,
    due_at     timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS auto_advance_schedule_due_idx
    ON auto_advance_schedule (due_at);

COMMENT ON TABLE auto_advance_schedule IS
    'Durable next-stage schedule for roster-scoped auto-progression (testing). '
    'A poller advances rows whose due_at has passed and rewrites/deletes them; '
    'survives restarts. next_stage in (RECEIVED, PREPARING, READY).';
