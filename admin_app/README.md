# CareVo Admin Dashboard

Internal platform-admin tool. Next.js 16 / React 19 / Tailwind 4 — same stack and
config as `gusto_pos/customer_app`. Clarity over polish; no design system.

## What it does

| Page | Backend |
| --- | --- |
| `/login` | `POST /api/v1/auth/login` (existing staff login) then `GET /api/v1/admin/me` |
| `/dashboard` — pending-restaurant queue, approve / reject | `GET /admin/outlets/pending`, `POST /admin/outlets/{id}/approve\|reject` |
| `/dashboard/outlets` — all outlets, filter by status | `GET /admin/outlets?status=` |
| `/dashboard/locked-orders` — locked orders across all outlets, unlock | `GET /admin/orders/locked`, `POST /admin/orders/{id}/unlock` |
| `/dashboard/audit` — append-only admin action trail | `GET /admin/audit-logs` |

## Auth

There is **no new auth system**. The dashboard uses the existing staff JWT from
`POST /api/v1/auth/login`. The backend gates every `/api/v1/admin/*` route on the
staff holding a role named `SUPER_ADMIN` (existing `roles` + `user_roles` tables).
An ordinary staff account authenticates fine and then gets `403` — the login page
surfaces that explicitly rather than showing an empty dashboard.

The token is kept in `localStorage`. That is a deliberate internal-tool tradeoff
(XSS-readable); it matches how the rest of this repo's web client works.

## Run locally

```bash
cd admin_app
cp .env.local.example .env.local     # point NEXT_PUBLIC_API_URL at your backend
npm install
npm run dev                          # http://localhost:3001
```

Port 3001 so it can run alongside `gusto_pos/customer_app` on 3000.

`NEXT_PUBLIC_API_URL` is inlined at **build** time. Changing it on a deployed
instance requires a rebuild, not a restart.

## Prerequisites before anything works

1. **Migration `003_admin_dashboard.sql` applied** (Checkpoint A — not yet run).
   Without it, `outlets.verification_status` and `admin_audit_logs` do not exist
   and the admin endpoints error.
2. **A `SUPER_ADMIN` grant** for at least one staff user — see the commented
   `INSERT INTO user_roles` at the bottom of migration 003. Separate approval.

## Notes

- `verification_status` (platform gate) and `is_visible` (owner's discovery
  toggle, migration 002) are independent. Approving an outlet does not change
  its visibility, and this dashboard never writes `is_visible`.
- Unlock mirrors the manual `UPDATE customer_orders SET is_locked=false,
  failed_attempts=0` documented in `gusto_pos/backend/OWNER_APP_README.md` —
  same effect, but gated and written to `admin_audit_logs`.
