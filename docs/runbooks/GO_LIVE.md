# Gusto Skip — Go-Live Runbook

Plain-language, numbered. Each step says who does it. "WHO: AGENT-DONE" means
this run already finished that step and the evidence is in the final report.
"WHO: ADI" means you run it yourself — the exact command or console path is
given. Nothing in this file contains a real credential, connection string,
or password. Placeholders are written as `<LIKE-THIS>`.

## 1. Neon: snapshot production before anything else

WHO: ADI

Console path only, no credentials typed into chat or any file:

1. Open the Neon console → your project → **Branches**.
2. Click **Create branch** → base it on the `production`/default branch,
   at the current head (latest point in time).
3. Name it something like `pre-migration-034-041-<today's date>`.
4. Confirm it was created. This branch is your rollback point — if
   anything in steps 3-5 goes wrong, you restore from here, not by trying
   to hand-write undo SQL.

## 2. Set the two environment variables, one command, at your own terminal

WHO: ADI

These two variables are read by `scripts/apply_migrations.py` and must
never be pasted into chat, committed to a file, or printed by any tool.
Open your own terminal (not this session) and set them for one command
only (PowerShell):

```powershell
$env:MIGRATE_DATABASE_URL = "<YOUR-NEON-PRODUCTION-CONNECTION-STRING>"
$env:MIGRATE_CONFIRM_HOST = "<THE-HOST-PART-OF-THAT-SAME-CONNECTION-STRING>"
```

`MIGRATE_CONFIRM_HOST` is a safety check: the tool refuses `--apply` unless
this exactly matches the host in `MIGRATE_DATABASE_URL`. It stops you from
running `--apply` against the wrong database by accident.

These variables live only in that terminal's process memory. Closing the
terminal clears them. Never write them into `.env`, a script, or a commit.

## 3. Dry run against production

WHO: ADI

```powershell
cd gusto_pos\backend
python scripts\apply_migrations.py
```

This changes nothing. Each migration file prints one of:

- `ALREADY_APPLIED NNN file.sql` — recorded in `schema_migrations` with a
  checksum that matches the file on disk. Nothing to do.
- `PENDING NNN file.sql` — not recorded yet. `--apply` would run it.
- `DRIFT NNN file.sql` — recorded, but the file on disk no longer matches
  what was recorded. Exit code 2. **Stop and investigate before doing
  anything else** — this means either the file changed after being applied,
  or the tracking table has a wrong entry.

On first run against production, `schema_migrations` does not exist yet, so
every one of 001-041 will show `PENDING`. That is expected — step 4 fixes it.

## 4. Baseline 001-033 (only if the predeploy SQL confirms it's needed)

WHO: ADI

First, run the predeploy check (read-only, SELECT-only, safe to run any
time) against production, using whatever SQL client you already use for
Neon (psql, Neon's SQL editor, etc.):

```
docs\ops\predeploy_check.sql
```

Expected result **before** baselining: `schema_migrations_exists = false`,
and the migration-034-037 columns on `outlets`
(`payment_prepaid_enabled`, `payment_pay_at_pickup_enabled`,
`payment_upi_manual_enabled`, `cashfree_unlocked`) and/or the 033-era
tables already exist (they were applied by hand, which is exactly why no
tracking table exists yet).

If and only if that's what you see, record 001-033 as already applied
without re-running their SQL:

```powershell
python scripts\apply_migrations.py --baseline-through 33
```

This refuses (exit 4) if `schema_migrations` already has any rows — so it
is safe to attempt even if you're unsure whether this step already ran.

If the predeploy SQL instead shows `schema_migrations_exists = true`,
skip this step — baselining already happened.

## 5. Apply 034-041, then check again

WHO: ADI

```powershell
python scripts\apply_migrations.py --apply
```

Each file runs in its own transaction. If one fails, everything before it
stays recorded and the tool stops (exit 4) — re-run after fixing the
cause; already-applied files are skipped automatically.

Then re-run `docs\ops\predeploy_check.sql` again. Expected now:
`schema_migrations_exists = true`, and `payment_events`,
`outlet_gateway_credentials`, `service_fee_ledger` all `exists = true`.

## 6. Confirm Render environment settings

WHO: ADI

In the Render dashboard, for the backend service, confirm:

| Variable | Required value |
|---|---|
| `CUSTOMER_AUTH_ENABLED` | `false` |
| `OTP_STUB_MODE` | `false` |
| `FIREBASE_ENABLED` | `true` |
| `PAYMENT_GATEWAY` | `cashfree` |
| `SERVICE_FEE_LEDGER_ENABLED` | unset, or `false` |
| `VENDOR_GATEWAY_ENABLED` | unset, or `false` |

Do not flip `SERVICE_FEE_LEDGER_ENABLED` to `true` yet — see step 12.

## 7. Deploy

WHO: ADI

```powershell
git push origin reconcile:21_7
```

Then wait for the Render deploy to finish (Render dashboard shows
"Live"). Health check:

```
GET https://gusto-pos-backend.onrender.com/health
```

Expected response: HTTP 200 with a small JSON body indicating the service
and database are up (exact shape depends on the current `/health` handler
— any 200 with no error field counts as healthy; a 5xx does not).

## 8. Verify auth posture after deploy

WHO: ADI

```
POST https://gusto-pos-backend.onrender.com/api/v1/customer/auth/verify-otp
```
with a deliberately wrong code. Expected: **HTTP 503** (the fail-closed
guard from migration/feature work already on `reconcile`, re-confirmed
live). A 200 or 4xx here means the guard did not deploy as expected — stop
and do not proceed to step 9.

Then open the already-published customer app (the live Play build) and
confirm Firebase phone-OTP login still works end to end against this same
backend.

## 9. Regression-test the published store app against the new backend

WHO: ADI

Before shipping any app update, open the **already-live** customer app
(not a new build) against the now-updated backend and check:

1. QR scan → menu loads for at least one outlet.
2. Add an item with a modifier → cart total is correct.
3. Checkout with each enabled payment mode (prepaid / pay-at-pickup /
   manual UPI, per that outlet's flags) → order places.
4. Order status screen polls and updates.
5. Phone-OTP login (Firebase) → succeeds.
6. Loyalty points / coupon display (if the outlet has them) → unaffected.

Any screen that breaks here is a backend regression, not an app bug — do
not proceed to step 10 until fixed.

## 10. Play Console

WHO: ADI

**Customer app:**
1. Play Console → your app → **Testing → Internal testing** → upload the
   AAB this run built (see the final report for its exact path).
2. Confirm the internal test passes, then **Promote** to the next track
   (closed/open/production) per your usual rollout policy.

**Owner app (first-ever Play upload):**
1. Play Console → **Create app** → fill in the basic details
   (`com.carevo.owner_app`, as confirmed by this run — must differ from
   the customer app's `com.carevo.customer_app`, and does).
2. Create a new **upload key** at your own terminal — this run deliberately
   did not do this; only you should hold this keystore:

```powershell
keytool -genkeypair -v -storetype PKCS12 -keystore <PATH-TO-NEW-UPLOAD-KEYSTORE.jks> -alias <KEY-ALIAS> -keyalg RSA -keysize 2048 -validity 10000
```
   (You'll be prompted for a keystore password and key details
   interactively — never type the password into chat or a file this
   assistant can read.)
3. Put the new key's SHA-1 into Play Console under **App integrity → App
   signing** (step 11 shows the command to read it).
4. Store listing items Play will require before review:
   - Content rating questionnaire
   - Data safety form
   - Privacy policy URL
   - A reviewer test login (a real outlet-owner account Play's reviewers
     can sign in with)
   - Tester emails for the internal testing track
5. First review after submission typically takes **several days** —
   budget for that before promising a launch date.

## 11. Print your upload-key SHA-1 to compare with Play Console

WHO: ADI

```powershell
keytool -list -v -keystore <PATH-TO-YOUR-KEYSTORE.jks> -alias <KEY-ALIAS>
```
Look for the line starting `SHA1:` and compare it character-for-character
with what Play Console shows under App signing.

## 12. After go-live: ongoing duty

WHO: ADI

- Keep `SERVICE_FEE_LEDGER_ENABLED` **off** on Render until at least one
  real, completed order has been tested end-to-end with it off — don't
  flip it on speculatively.
- Daily check (until this becomes routine): query for
  - orders marked refund-due that haven't been refunded yet,
  - orders marked completed without a matching successful payment event.
  Both of these are exactly what `payment_events` / `service_fee_ledger`
  (migrations 039/041) exist to make queryable — write the two queries
  once you're comfortable with the schema, save them next to
  `docs\ops\predeploy_check.sql`, and run them daily.
