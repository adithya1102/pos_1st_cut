# POS Registration Link (Gusto Skip <-> Native Gusto POS)

Replaces open sign-up on the Native Gusto POS with a one-time Registration
ID issued from the Gusto Skip `owner_app`. Added on branch `21_7`,
2026-11-24. Migration `044_pos_registration.sql` (NOT YET APPLIED anywhere —
see Checkpoint A in the session that introduced this).

## Flow

1. Owner opens **Connect your POS** in `owner_app`
   (`owner_app/lib/screens/connect_pos_screen.dart`). Every time this screen
   opens it calls `POST /api/v1/owner/pos-registration-code`, which mints a
   **new** code and revokes any earlier unused one for that outlet.
2. Owner types the code into the POS at `/register`.
3. The POS backend calls `POST /api/v1/pos-link/verify` with the code. On
   success it gets back the outlet + owner details (not yet consumed) and
   shows the Create Account screen, prefilled.
4. On account creation, the POS calls `POST /api/v1/pos-link/consume` with
   the `registration_ref` from step 3 and a `pos_install_id`. This is what
   actually marks the code used and stamps `outlets.pos_registered_at`.

## Endpoints (mounted under `/api/v1`, `app/modules/pos_link/controller.py`)

| Route | Auth | Notes |
|---|---|---|
| `POST /owner/pos-registration-code` | Owner/Manager staff JWT (`carevo_pos.deps.get_outlet_manager` — the same allow-list `/pos/*` already uses) | 403 if the outlet's `verification_status != 'active'` (not yet admin-approved) |
| `POST /pos-link/verify` | **Public** | Body `{code}`. Returns `{registration_ref, outlet, owner}`. Does NOT consume. |
| `POST /pos-link/consume` | **Public** | Body `{registration_ref, pos_install_id}`. Idempotent per `pos_install_id`. |

## Why there is no HMAC / shared secret

The original contract specified server-to-server HMAC signing
(`X-CareVo-Timestamp` / `X-CareVo-Signature`, `POS_LINK_SHARED_SECRET`).
This was deliberately dropped: **a secret baked into a desktop installer is
not a secret** — any Windows user can extract it from the binary/`.env` the
installer ships. `/pos-link/verify` and `/pos-link/consume` are public
endpoints instead, protected by:

- Code entropy — CSPRNG, 8 characters from a 32-symbol alphabet
  (`ABCDEFGHJKMNPQRSTVWXYZ23456789`, excludes `0/O/1/I/L`) → ~2^39 space.
- A 15-minute TTL (`POS_REG_CODE_TTL_MINUTES`), single use.
- Rate limiting, two layers (see below).
- Every failure (unknown code, expired, consumed, revoked, bad
  `registration_ref`) returns the **identical** `400 {"detail": "Code not
  valid"}` body, so a caller cannot enumerate which case it hit. No code or
  `registration_ref` is ever logged.

Phase B (the POS side) therefore needs only `SKIP_LINK_BASE_URL` — no shared
secret to provision or rotate.

## Rate limiting

Two independent layers, same reasoning as every other limiter in this repo
(single-process, in-memory, no Redis — see `AGENT_GUARDRAILS.md`):

1. **Per-IP, in-memory** (`app/modules/pos_link/service.py
   :_pos_link_failure_hits`): 5 failed attempts / 15 minutes
   (`POS_LINK_RATE_LIMIT_PER_IP`, `POS_LINK_RATE_LIMIT_WINDOW_SECONDS`).
   Forgotten on restart/redeploy.
2. **DB-backed global backstop** (`pos_link_rate_limit_state`, migration
   044, single row): 50 failures / hour across ALL IPs trips a 10-minute
   global cooldown (`POS_LINK_GLOBAL_FAILURE_LIMIT`,
   `POS_LINK_GLOBAL_FAILURE_WINDOW_SECONDS`,
   `POS_LINK_GLOBAL_COOLDOWN_SECONDS`). Survives a restart.

Only **failed** verify/consume calls increment either counter — a POS
legitimately retrying its own successful flow is never penalised.

## Modes (`POS_REG_MODE`, server-side only)

- `random` (default) — the flow above, as specified.
- `fixed-test` — the minted code is always the literal `"1234"`, reusable
  (never marked consumed, so any number of `pos_install_id`s can consume
  it), TTL ignored. **Never appears in any client code or release build** —
  it only ever exists as a value the backend generates at runtime.
  Fail-closed at process startup:
  `validate_pos_link_startup_posture` (`app/core/config.py`) raises
  `PosLinkConfigError` and refuses to start if `POS_REG_MODE=fixed-test`
  outside `NON_PRODUCTION_ENVS = {"dev", "development", "local", "test"}` —
  the exact same convention `validate_auth_posture` /
  `validate_gateway_startup_posture` already use, wired into
  `app/main.py`'s `on_startup`.

## Env vars (`.env`, never committed)

| Var | Default | Notes |
|---|---|---|
| `POS_REG_MODE` | `random` | `fixed-test` refused outside dev/test envs |
| `POS_REG_CODE_TTL_MINUTES` | `15` | |
| `POS_LINK_RATE_LIMIT_PER_IP` | `5` | per `POS_LINK_RATE_LIMIT_WINDOW_SECONDS` (`900`) |
| `POS_LINK_GLOBAL_FAILURE_LIMIT` | `50` | per `POS_LINK_GLOBAL_FAILURE_WINDOW_SECONDS` (`3600`) |
| `POS_LINK_GLOBAL_COOLDOWN_SECONDS` | `600` | |

No `POS_LINK_SHARED_SECRET` — removed from the contract, see above.

## Schema (migration 044)

- `pos_registration_codes` — `code_hash` (SHA-256 of the code + `SECRET_KEY`
  as pepper, never the plain code), `mode`, `expires_at`, `consumed_at`,
  `revoked_at`, `registration_ref_hash`, `pos_install_id`, `failed_attempts`.
- `outlets.pos_registered_at` — stamped on successful consume.
- `pos_link_rate_limit_state` — single-row global failure counter.

**Not yet applied to any database.** Per `AGENT_GUARDRAILS.md` Checkpoint A,
the SQL diff was shown for approval before being run anywhere, including the
local `carevo_test` database used by `tests/reset_test_db.py`.

## Tests

- `tests/test_api_pos_link_posture.py` — unit-level, no DB: the
  `POS_REG_MODE=fixed-test` fail-closed matrix. **21/21 passing** (verified
  this session; no DB required).
- `tests/test_api_pos_link.py` — HTTP-level, needs migration 044 applied to
  `carevo_test`: valid/expired/wrong/reused code, rate limiting (429),
  unapproved-outlet refusal, regenerate-revokes-old, idempotent consume,
  fixed-test mode. **Not yet run** — blocked on the Checkpoint A migration
  approval above.

## owner_app

`lib/screens/connect_pos_screen.dart` + `lib/services/pos_link_service.dart`.
Mints a fresh code every time the screen opens (same unconditional mint the
backend does), shows a live countdown, a copy-to-clipboard button, and a
"not yet approved" message on a 403 from the mint call. No hardcoded code,
no test flag, anywhere in the file — confirmed by `flutter analyze` (33
pre-existing issues, none in the new files or edited lines).
