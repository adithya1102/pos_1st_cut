"""SUPER_ADMIN gate for the CareVo Admin Dashboard.

This is NOT a new auth system. It layers on top of the existing staff JWT:
`get_current_staff` (app/modules/carevo_customer/deps.py) does all token work,
and this module only adds a role check on top of the resulting User.

Super-admin-ness is carried by the EXISTING roles table + user_roles m2m —
a staff account is a super admin iff it holds a role named SUPER_ADMIN.
No new column on users, no second login endpoint, no second token type.
"""
from fastapi import Depends, HTTPException, status

from app.modules.carevo_customer.deps import get_current_staff
from app.modules.users.model import User

SUPER_ADMIN_ROLE = "SUPER_ADMIN"


def is_super_admin(user: User) -> bool:
    # User.roles is lazy="selectin", so it is already loaded here.
    return any((r.name or "").upper() == SUPER_ADMIN_ROLE for r in (user.roles or []))


async def get_current_super_admin(staff: User = Depends(get_current_staff)) -> User:
    """Staff bearer + SUPER_ADMIN role. 403 for any other authenticated staff.

    Unlike /pos/*, super admins are deliberately NOT scoped to an outlet —
    they act across every outlet, and typically have outlet_id = NULL.
    """
    if not is_super_admin(staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SUPER_ADMIN role required",
        )
    return staff
