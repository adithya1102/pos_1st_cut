-- 037_outlet_owner_marker.sql
--
-- users.is_outlet_owner — a POSITIVE marker for "this account runs its outlet".
--
-- ADDITIVE ONLY. One column, one default, no backfill. No existing column is
-- altered, no row is read or written.
--
-- ============================================================================
-- WHY THIS COLUMN HAS TO EXIST
-- ============================================================================
-- Migration 035 shipped an owner-facing settings route gated by
-- may_manage_outlet_settings, and that gate was a DENY-LIST: it refused
-- WAITER and KITCHEN by name and allowed everything else, including an account
-- with no roles at all. The reasoning was that a role-less account can only
-- have been produced by register_owner, so it must be the outlet's owner.
--
-- That reasoning was wrong, and the review found the escalation it opens:
--
--   1. any staff account can reach POST/PUT /api/v1/users (staff-authed
--      router-wide, no further check),
--   2. so a waiter can create a NEW account with role_ids: [],
--   3. that account is role-less,
--   4. so the deny-list allows it,
--   5. and it can now rewrite the outlet's payment settings — including the
--      UPI VPA that customers' money is sent to.
--
-- The hole is not the deny-list alone; it is the deny-list PLUS an open user
-- table. Both halves are closed: /users is locked down (see users/controller),
-- and this column replaces "has no roles" with a fact somebody deliberately
-- asserted.
--
-- ============================================================================
-- WHY NOT JUST USE THE ROLES TABLE
-- ============================================================================
-- Because the roles are assigned by a different path than the one that creates
-- owners. StaffService.create_staff maps a staff member to Owner/Waiter/
-- Kitchen, but CarevoService.register_owner — the function that actually
-- provisions a restaurant — writes a users row and no user_roles row at all.
-- Granting the Owner role there would also have worked; a column was chosen
-- because it says exactly one thing ("runs this outlet"), it cannot be
-- confused with the Owner ROLE used by the PIN-reset gate, and it is one
-- UPDATE for an operator to set on an existing account.
--
-- DEFAULT false, and DELIBERATELY NO BACKFILL. A migration that flipped this
-- true for every account with no roles would re-create the exact hole it
-- exists to close — the role-less accounts are the ones whose provenance is
-- unknown. Existing owners are flagged ONE AT A TIME by a human who knows
-- which account belongs to the restaurant:
--
--   UPDATE users SET is_outlet_owner = true WHERE username = '<username>';
--
-- Until that is run, an existing owner falls back to the OWNER/MANAGER/ADMIN
-- role check or to SUPER_ADMIN. The cost of the missing backfill is that some
-- owners must be flagged before they can change their payment settings; the
-- cost of having written one would be that anybody who ever created a
-- role-less account keeps their access. The first is a support ticket, the
-- second is a vulnerability.
--
-- ============================================================================
-- ROLLBACK
-- ============================================================================
--   ALTER TABLE users DROP COLUMN is_outlet_owner;
--
-- Clean at any time. It loses the flags, which means every owner has to be
-- re-flagged — recoverable, but the gate refuses them until it is done, so do
-- not roll this back while the owner settings route is live.
--
-- NOT ORM-MAPPED? IT IS. This is the one exception on this branch, and
-- deliberately: may_manage_outlet_settings reads it off the User object the
-- auth dependency already loaded, on every call to a gated route. Reading it
-- with raw SQL would mean an extra query per request on an authorisation path,
-- and an authorisation check that can fail open if that query errors. Mapping
-- it means the column must exist before the code deploys — so THIS MIGRATION
-- RUNS BEFORE THE DEPLOY, unlike 034-036.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_outlet_owner boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN users.is_outlet_owner IS
    'TRUE when this staff account runs its outlet and may change the '
    'restaurant''s own configuration (payment modes, and the staff of that '
    'outlet). Set by CarevoService.register_owner for accounts it creates, and '
    'by hand for accounts that predate migration 037. DEFAULT false with NO '
    'BACKFILL on purpose: before 037 the owner gate allowed any ROLE-LESS '
    'account, which a waiter could mint through the then-open /api/v1/users, '
    'so "has no roles" is not evidence of ownership and must not be treated as '
    'though it were.';
