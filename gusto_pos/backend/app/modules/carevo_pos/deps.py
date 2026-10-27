"""Who, inside one outlet, may change how that outlet takes money.

This is NOT a new auth system. `get_current_staff` does all the token work and
`_require_outlet` already scopes every /pos route to the caller's own outlet;
this adds one role check on top of the resulting User, in the same shape
carevo_admin/deps.py adds the SUPER_ADMIN check.

=============================================================================
WHY THIS IS A DENY-LIST AND NOT THE ALLOW-LIST IT LOOKS LIKE IT SHOULD BE
=============================================================================
The obvious implementation is "allow OWNER or MANAGER, refuse everyone else".
That would lock every real restaurant owner out of their own settings screen,
because in this schema an outlet's owner account has NO ROLE ROW AT ALL:

  * CarevoService.register_owner inserts into `users` naming only id, username,
    hashed_password, is_active, outlet_id, email and created_at
    (carevo_customer/service.py:4492-4498). No user_roles row is written.
  * No migration backfills roles for outlet staff — 003_admin_dashboard.sql
    only ever assigns SUPER_ADMIN, and does so by hand in a commented example.
  * The test fixture reproduces production faithfully: conftest.py gives the
    SUPER_ADMIN role to the admin user and leaves the owner user role-less.

So "holds the Owner role" is not a property real owners have. What IS reliably
true is the other side: staff created through POST /staff DO get a role, mapped
by StaffService._ROLE_MAP (staff/service.py:11) to Owner, Waiter or Kitchen.
Waiters and kitchen staff are therefore identifiable by what they hold, and the
owner is identifiable by holding nothing.

The gate is built on that asymmetry:

  SUPER_ADMIN                      -> allow (acts across every outlet)
  holds OWNER / MANAGER / ADMIN    -> allow (explicitly privileged)
  holds WAITER or KITCHEN          -> 403   (the requirement this exists for)
  holds no role at all             -> allow (the outlet's own owner account)

The last line is the deviation and it is load-bearing: without it the feature
cannot be used by anybody it was built for. It is also narrow — a role-less
account can only have been created by register_owner or seeded by hand, both of
which mean "this is the outlet", and it is still outlet-scoped by
_require_outlet, so it can only ever change its OWN restaurant's settings.

ROLE_NAMES ARE MATCHED CASE-INSENSITIVELY, matching is_super_admin and
_PIN_ADMIN_ROLES, because the seeded names are title-case ("Owner") while the
constants everywhere else are upper.
"""
from fastapi import Depends, HTTPException, status

from app.modules.carevo_admin.deps import is_super_admin
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.users.model import User

#: Roles that may administer the outlet's own configuration. ADMIN is included
#: because _ROLE_MAP turns a staff member created as "Admin" into "Owner", and
#: _PIN_ADMIN_ROLES already treats the three as equivalent for the same reason.
OUTLET_ADMIN_ROLES = {"OWNER", "MANAGER", "ADMIN"}

#: Roles that must NEVER reach payment settings. A waiter changing how the
#: restaurant gets paid, or a kitchen tablet doing it by accident, is the
#: specific thing this gate exists to prevent.
OUTLET_STAFF_ROLES = {"WAITER", "KITCHEN"}


def _role_names(user: User) -> set[str]:
    # User.roles is lazy="selectin", so it is already loaded here.
    return {(r.name or "").upper() for r in (user.roles or [])}


def may_manage_outlet_settings(user: User) -> bool:
    """True when this staff account may change its outlet's configuration."""
    if is_super_admin(user):
        return True
    names = _role_names(user)
    if names & OUTLET_ADMIN_ROLES:
        return True
    if names & OUTLET_STAFF_ROLES:
        return False
    # No role at all — the outlet's own owner account. See the module docstring
    # for why this is an allow and not a refusal.
    return not names


async def get_outlet_manager(staff: User = Depends(get_current_staff)) -> User:
    """Staff bearer + permission to administer this outlet. 403 otherwise.

    Deliberately does NOT resolve the outlet itself: every route using this
    still calls _require_outlet, so scoping stays in one place and this
    dependency answers only the role question.
    """
    if not may_manage_outlet_settings(staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the restaurant owner or a manager can change this.",
        )
    return staff
