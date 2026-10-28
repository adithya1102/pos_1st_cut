"""Who, inside one outlet, may change how that outlet takes money.

This is NOT a new auth system. `get_current_staff` does all the token work and
`_require_outlet` already scopes every /pos route to the caller's own outlet;
this adds one role check on top of the resulting User, in the same shape
carevo_admin/deps.py adds the SUPER_ADMIN check.

=============================================================================
AN ALLOW-LIST. THE PREVIOUS DENY-LIST WAS A PRIVILEGE ESCALATION.
=============================================================================
Migration 035 shipped this gate as a DENY-LIST: it refused WAITER and KITCHEN
by name and allowed everything else, INCLUDING AN ACCOUNT WITH NO ROLES AT
ALL. The argument was that a role-less account could only have been produced
by CarevoService.register_owner, so it had to be the outlet's own owner, and
that this was "narrow".

THAT ARGUMENT WAS WRONG AND THE CLAIM OF NARROWNESS IS WITHDRAWN. It rested on
provenance the gate could not actually check, and the provenance was forgeable:

  1. every route in /api/v1/users was staff-authed router-wide and had no
     further check, so ANY staff account could reach POST and PUT there;
  2. a waiter could therefore create a new account with `role_ids: []`;
  3. that account is role-less;
  4. the deny-list allowed it;
  5. and it could rewrite the outlet's payment settings — including the UPI
     VPA that customers' money is sent to.

Five steps, all of them inside one outlet, none of them requiring SUPER_ADMIN.
"A role-less account can only have been created by register_owner" was simply
not true while anybody could create one.

Both halves are now closed. /api/v1/users is locked down (see
users/controller.py for the rules and the caller audit behind them), and this
gate no longer infers ownership from an ABSENCE. It requires one of three
positive facts:

  SUPER_ADMIN                        -> allow (acts across every outlet)
  role OWNER / MANAGER / ADMIN       -> allow (explicitly privileged)
  users.is_outlet_owner = true       -> allow (migration 037; the restaurant's
                                        own account, asserted deliberately)
  anything else, including no roles  -> 403

The cost is real and was accepted: an owner account created BEFORE migration
037 has neither a role nor the flag, so it is refused until a human flags it
with

    UPDATE users SET is_outlet_owner = true WHERE username = '<username>';

There is deliberately NO BACKFILL. Flipping the flag true for every role-less
account would restore the exact hole this closes, because the role-less
accounts are precisely the ones whose provenance is unknown. A support ticket
per existing owner is the cheaper mistake.

ROLE NAMES ARE MATCHED CASE-INSENSITIVELY, matching is_super_admin and
_PIN_ADMIN_ROLES, because the seeded names are title-case ("Owner") while the
constants everywhere else are upper.
"""
from fastapi import Depends, HTTPException, status

from app.modules.carevo_admin.deps import is_super_admin
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.users.model import User

#: Roles that may administer their own outlet's configuration. ADMIN is
#: included because StaffService._ROLE_MAP turns a staff member created as
#: "Admin" into "Owner", and _PIN_ADMIN_ROLES already treats the three as
#: equivalent for the same reason.
OUTLET_ADMIN_ROLES = {"OWNER", "MANAGER", "ADMIN"}


def _role_names(user: User) -> set[str]:
    # User.roles is lazy="selectin", so it is already loaded here.
    return {(r.name or "").upper() for r in (user.roles or [])}


def may_manage_outlet_settings(user: User) -> bool:
    """True when this staff account may change its outlet's configuration.

    An ALLOW-LIST: every branch is a positive fact about the account. There is
    no fall-through that grants access, so a new kind of account — however it
    was created — is refused until somebody says otherwise.
    """
    if is_super_admin(user):
        return True
    if bool(getattr(user, "is_outlet_owner", False)):
        return True
    return bool(_role_names(user) & OUTLET_ADMIN_ROLES)


async def get_outlet_manager(staff: User = Depends(get_current_staff)) -> User:
    """Staff bearer + permission to administer this outlet. 403 otherwise.

    Deliberately does NOT resolve the outlet itself: every route using this
    still calls _require_outlet, so scoping stays in one place and this
    dependency answers only the "may you" question.
    """
    if not may_manage_outlet_settings(staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the restaurant owner or a manager can change this.",
        )
    return staff
