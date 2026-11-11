# Payment tab runbook

What the three Payment-tab toggles do, the machine-readable reasons a switch
can be unavailable, the CASHFREE_ONLY rule for this release, and the
migrations that must already be applied.

## The three toggles

| Toggle (owner app label) | Owner flag | Customer-facing wire value | Owner app card |
|---|---|---|---|
| Pay when collecting | `payment_pay_at_pickup_enabled` | `PAY_AT_PICKUP` | `owner_app/lib/screens/payment_tab_screen.dart` — `_PickupCard` |
| Your own UPI | `payment_upi_manual_enabled` | `UPI_MANUAL` | same file — `_UpiCard` |
| Payment gateway | `payment_prepaid_enabled` | `PREPAID` | same file — `_GatewayCard` |

Each switch sends `PATCH /api/v1/pos/outlet/payment-methods` the instant it is
flipped (full desired state — the route requires all three flags on every
call), shows a progress spinner, and on any server error reverts to its
previous value and shows the server's own message. None of the three money
rules changed to build this: they are the SAME four rules
`set_owner_payment_methods` has always enforced
(`gusto_pos/backend/app/modules/carevo_customer/service.py`):

1. At least one method must stay on (422 `NO_PAYMENT_METHOD`).
2. The gateway cannot be turned on while locked (409 `CASHFREE_LOCKED`).
3. UPI needs a VPA, a payee name, and an attestation (422
   `UPI_DETAILS_REQUIRED` / `UPI_ATTESTATION_REQUIRED`).
4. Changing the VPA voids the old attestation.

## Per-mode unavailable reasons (additive GET fields)

`GET /api/v1/pos/outlet/payment-methods` now also returns, per mode:

| Field | Meaning |
|---|---|
| `gateway_available` / `gateway_unavailable_reason` | `false` / `CASHFREE_LOCKED` when `cashfree_unlocked` is false. |
| `pay_at_pickup_available` / `pay_at_pickup_unavailable_reason` | `false` / `CASHFREE_ONLY_MODE` while the platform-wide `CASHFREE_ONLY` switch is on. |
| `upi_manual_available` / `upi_manual_unavailable_reason` | `false` / `CASHFREE_ONLY_MODE` under `CASHFREE_ONLY`, or `false` / `UPI_NOT_SET_UP` when the VPA/payee/attestation is incomplete. |

These are read-only projections of the existing rules above — they do not add
a new refusal, they let the owner app grey a switch BEFORE a tap instead of
after a 409/422/403.

## CASHFREE_ONLY must stay unset or false in this mode

The Payment tab mission runs with three independently toggleable methods,
which is the opposite of what `CASHFREE_ONLY=true` (`gusto_pos/backend/app/core/config.py`)
is for: that switch makes Cashfree prepaid the ONLY path on the whole
platform and 403s any attempt to turn pay-at-pickup or UPI on
(`CASHFREE_ONLY_MODE`). Leave the environment variable unset, or explicitly
`false`, for every outlet this release touches. `CarevoService.payment_methods_for`
short-circuits to `[PAY_PREPAID]` (or nothing) the instant it is true —
checked before this release's three-mode logic is even reached.

## Migrations that must be applied first

Migrations 034 through 038 must already be applied before this release goes
out (run `python tests/reset_test_db.py` to verify locally — it applies
every file in `migrations/` and prints the count; the `migrations/` directory
on this branch has grown to 41 files since this runbook was written, so the
printed count is 41, not 38. `tests/reset_test_db.py:34`'s own docstring
still says "001 through 038" — out of scope here, as it is a test script,
not a documentation file):

| Migration | What it adds |
|---|---|
| 034 | `payment_pay_at_pickup_enabled`, the pay-at-pickup flow |
| 035 | `payment_upi_manual_enabled`, `upi_vpa`, `upi_payee_name`, `upi_attested_at`, the owner self-serve PATCH route |
| 036 | `cashfree_unlocked` defaults to `false` for newly created outlets |
| 037 | `users.is_outlet_owner`, the positive marker the settings-route gate now requires |
| 038 | `payment_amount_mismatch` safeguard (unrelated money-path fix, bundled in the same migration run) |

This release adds NO new migration — the per-mode availability fields are
derived entirely from columns 034–037 already created; nothing new is
written to the database.

## Owner app navigation

Bottom nav order: Orders, Menu, **Payment**, Offers
(`owner_app/lib/screens/home_screen.dart`). The older `/payment-modes` route
(`owner_app/lib/screens/payment_modes_screen.dart`, reached from Outlet
settings → "Payment modes") is unchanged and still works — it is a second,
independent way to reach the same PATCH route, not superseded by the tab.

## Customer app checkout

Checkout re-fetches payment methods every time it opens (via the existing
`GET /customer/menu/{outlet_id}` call, which already returns
`payment_methods`), rendering them in a fixed order — gateway, own UPI, pay
at pickup — regardless of what order the server lists them in, with the
gateway option preselected when offered. A `409 PAYMENT_METHOD_UNAVAILABLE`
from `POST /customer/orders` triggers the same refetch, shows "This payment
option is no longer available. Please choose another.", and leaves the cart
and any scheduled pickup time untouched.
