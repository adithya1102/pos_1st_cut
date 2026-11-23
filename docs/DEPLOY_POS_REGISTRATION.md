# Deploy runbook: POS registration link (Skip side)

**This document is a plan. Nothing in it has been run.** Every command
below is written to be copy-pasted by a human who has read it first and
confirmed the target host, per AGENT_GUARDRAILS.md §1 — do not run any
command against a Neon host without first confirming which branch it is.

Current repo state at the time of writing (see the session's Task 1
preflight): branch `fix/upi-ref-accept-sheet`, remote `origin`
(`github.com/adithya1102/pos_1st_cut.git`). **`render.yaml`'s Skip service
is pinned to branch `"21_7"`**, not this branch — a Render blueprint
auto-deploy will deploy `21_7`, not whatever is currently checked out. If
this work needs to ship, it must land on `21_7` (merge or fast-forward),
not be deployed from a feature branch. This mismatch is reported, not
fixed, by this runbook.

---

## 1. Apply migration 044 to a Neon DEV branch

Per AGENT_GUARDRAILS.md §1: Neon dev and prod share database name
(`neondb`) and user; only the `ep-...` host in the connection string tells
them apart. **Read the actual `DATABASE_URL` from wherever the dev branch's
credentials are kept (Neon dashboard, 1Password, etc.) immediately before
running anything — never assume a string is "dev" because someone
described it that way.**

```bash
cd gusto_pos/backend

# 1a. Identify the branch BEFORE anything else. Confirm the ep-... host is
#     NOT ep-morning-meadow-ao6m0otk-pooler (that is prod).
python -c "from urllib.parse import urlsplit; import os; print(urlsplit(os.environ['MIGRATE_DATABASE_URL'].replace('+asyncpg','')).hostname)"

# 1b. Dry run first (default mode, changes nothing):
MIGRATE_DATABASE_URL="<dev branch connection string>" \
  python scripts/apply_migrations.py
# Expect: PENDING 044 044_pos_registration.sql (and nothing else pending,
# assuming 001-043 are already applied on this branch).

# 1c. Apply, with the host-confirmation gate the tool itself enforces:
MIGRATE_DATABASE_URL="<dev branch connection string>" \
  MIGRATE_CONFIRM_HOST="<the exact ep-... host from step 1a>" \
  python scripts/apply_migrations.py --apply
# Expect: APPLIED 044 044_pos_registration.sql
```

## 2. Verify on the dev branch

```bash
# Confirm the new tables/column exist:
psql "<dev branch connection string>" -c "\d pos_registration_codes"
psql "<dev branch connection string>" -c "\d pos_link_rate_limit_state"
psql "<dev branch connection string>" -c "SELECT column_name FROM information_schema.columns WHERE table_name='outlets' AND column_name='pos_registered_at';"

# Confirm the singleton rate-limit row exists (migration's own INSERT):
psql "<dev branch connection string>" -c "SELECT id, failure_count, cooldown_until FROM pos_link_rate_limit_state;"
# Expect exactly one row: id=1, failure_count=0, cooldown_until=NULL.
```

## 3. Neon PRODUCTION: snapshot branch, then migrate

**Never run a migration against prod without a snapshot to roll back to.**

```bash
# 3a. Create the pre-migration snapshot branch (Neon CLI; needs
#     NEON_API_KEY and the project id — not invented here):
neonctl branches create \
  --project-id <NEON_PROJECT_ID> \
  --name pre-migration-2026-11-24 \
  --parent main    # or whatever the prod branch's name actually is

# 3b. Identify prod's host explicitly (must equal
#     ep-morning-meadow-ao6m0otk-pooler per AGENT_GUARDRAILS.md):
python -c "from urllib.parse import urlsplit; import os; print(urlsplit(os.environ['MIGRATE_DATABASE_URL'].replace('+asyncpg','')).hostname)"
# This MUST print a host starting with ep-morning-meadow-ao6m0otk-pooler
# before proceeding. If it does not, STOP -- you are not pointed at prod
# and should not run the prod steps below.

# 3c. Dry run:
MIGRATE_DATABASE_URL="<prod connection string>" \
  python scripts/apply_migrations.py

# 3d. Apply, same host-confirmation gate:
MIGRATE_DATABASE_URL="<prod connection string>" \
  MIGRATE_CONFIRM_HOST="ep-morning-meadow-ao6m0otk-pooler.<region>.aws.neon.tech" \
  python scripts/apply_migrations.py --apply

# 3e. Verify, same three checks as step 2, against the prod connection string.
```

## 4. Deploy the Skip backend (Render service `gusto-pos-backend`)

**Finding, not a step to perform:** `render.yaml` has NO `preDeployCommand`
and the `startCommand` is a bare `uvicorn app.main:app ...` — this service
does **not** run migrations automatically on deploy, unlike the POS repo's
Docker CMD. Migration 044 must already be applied (steps 1-3 above) before
this deploy, or the new routes will 500 against a database missing their
tables.

Before triggering the deploy, confirm **in the Render dashboard
Environment tab** — not just `render.yaml`, which the file's own
`CUSTOMER_AUTH_ENABLED` comment documents as able to diverge from the live
dashboard value:

- `APP_ENV` is **unset or a production value** (never `dev`,
  `development`, `local`, or `test`).
- `POS_REG_MODE` is **unset or `random`** (never `fixed-test` — the app
  refuses to start otherwise; see `validate_pos_link_startup_posture`).

Both are currently absent from `render.yaml` entirely, which defaults to
the safe state (`APP_ENV` unset → `"production"`; `POS_REG_MODE` unset →
`"random"`) — but the dashboard is the authority, confirm there, not here.

Deploy (git push to `21_7`, or Render's manual deploy button — this
runbook does not trigger either).

## 5. Render dashboard: no new env var needed on the Skip side

The Skip backend introduces no new required env var for this feature
(`POS_REG_MODE`, `POS_REG_CODE_TTL_MINUTES`, and the `POS_LINK_*` rate-limit
settings all have safe defaults — see `app/core/config.py`). Nothing to set
here; this step exists only to say so explicitly, since the POS side (its
own runbook) does need a new var (`SKIP_LINK_BASE_URL`) pointed at this
service's deployed URL.

## 6. Smoke tests (curl)

Run these against the deployed URL once steps 1-4 are done. Secrets/values
redacted — fill in a real test outlet/owner and never commit a real code.

```bash
BASE="https://gusto-pos-backend.onrender.com/api/v1"

# Health:
curl -s "$BASE/../"   # root, not /health -- see app/main.py's root handler

# Verify with a deliberately wrong code (expect 400, generic body):
curl -s -i -X POST "$BASE/pos-link/verify" -H "Content-Type: application/json" -d '{"code":"ZZZZ-9999"}'

# Mint requires a real owner bearer token for an approved outlet -- not
# something to fabricate in a smoke test script; do this once by hand
# through owner_app against a real staging outlet, then verify + consume
# with the resulting code.
```

## 7. Rollback

- **Render deploy:** use Render's "Rollback to previous deploy" on the
  `gusto-pos-backend` service — this reverts code only, not the database.
- **Migration 044 on a Neon branch:** the migration is purely additive
  (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`) — rolling back
  code without rolling back the schema is safe; the new tables/column
  simply go unused. If the schema itself must be reverted (e.g. the feature
  is being pulled entirely), the migration file's own trailing comment
  lists the manual `DROP` statements — run them by hand, never
  automatically, and only after confirming (again, by host) which branch
  you are on.
- **Neon production:** if anything about the migration or the deploy went
  wrong, restore from the `pre-migration-2026-11-24` snapshot branch
  created in step 3a (Neon's branch-restore flow), rather than attempting
  to hand-reverse data changes.
