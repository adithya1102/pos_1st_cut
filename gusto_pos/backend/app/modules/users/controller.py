from typing import Any
from uuid import UUID
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.carevo_admin.deps import is_super_admin
from app.modules.carevo_customer.deps import get_current_staff
from app.modules.carevo_pos.deps import may_manage_outlet_settings
from app.modules.users.model import User
from app.modules.users.schema import UserCreate, UserRead
from app.modules.users.service import UserService


# STAFF-ONLY ROUTER-WIDE, AND NOW SCOPED AND ROLE-GATED PER ROUTE.
#
# The router-wide `get_current_staff` closed the unauthenticated hole. It was
# NOT enough, and the review found the escalation that remained: every route
# here was reachable by ANY staff account with no further check, so
#
#   1. a waiter could POST /users with role_ids: [] and a chosen outlet_id,
#   2. producing a role-less account, which
#   3. the owner-settings gate then allowed (it was a deny-list), letting that
#      account rewrite the outlet's UPI VPA;
#   and more directly:
#   4. a waiter could PUT /users/{their own id} with role_ids: [<Owner>] and
#      simply promote themselves.
#
# Both are closed here. The rules, in one place:
#
#   * SUPER_ADMIN may do anything, across every outlet.
#   * An OUTLET MANAGER (OWNER/MANAGER/ADMIN role, or is_outlet_owner) may
#     create, read, update and delete staff ONLY inside their own outlet_id,
#     and may not grant roles — role_ids is SUPER_ADMIN-only, because granting
#     a role is how you escalate.
#   * NOBODY may change their OWN roles or their OWN outlet_id, including a
#     super admin: self-promotion and self-relocation are the two edits with no
#     legitimate use, and refusing them costs nothing (another admin can).
#   * Listing returns only the caller's own outlet unless SUPER_ADMIN.
#
# CALLER AUDIT (why locking this down breaks nothing):
#   owner_app/lib     — no reference to /users. Staff are managed via /staff.
#   customer_app/lib  — no reference; it never touches staff accounts.
#   admin_app (Next)  — no reference in app/, components/ or lib/.
#   GustoPOS, GustoWaiter, dashboard_app, mcp_server — no reference.
# The only callers anywhere are gusto_pos/backend/test_api_user.py and
# test_api_user2.py, two ad-hoc scripts at the backend ROOT which pytest never
# collects (pytest.ini sets `testpaths = tests`) and which point at a
# hand-started server on port 8001. Nothing in production calls this router,
# which is what makes a change this restrictive safe here.
router = APIRouter(prefix="/users", dependencies=[Depends(get_current_staff)])

#: Fields only a SUPER_ADMIN may write, because each is a way to escalate:
#: roles grant privilege, outlet_id moves an account into another restaurant.
_PRIVILEGED_FIELDS = ("role_ids", "outlet_id")


def _require_manager(actor: User) -> None:
    """Reject anybody who is not at least an outlet manager."""
    if is_super_admin(actor):
        return
    if may_manage_outlet_settings(actor):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the restaurant owner or a manager can manage staff.",
    )


def _require_own_outlet(actor: User, outlet_id) -> None:
    """A manager may only act inside their own outlet.

    404 rather than 403 for a foreign outlet would be the pattern used
    elsewhere for ORDERS, but staff accounts are different: the caller already
    supplied the outlet_id here, so there is nothing to leak by naming the
    refusal, and a 403 tells an honest manager what went wrong.
    """
    if is_super_admin(actor):
        return
    if actor.outlet_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not assigned to an outlet.",
        )
    if outlet_id is not None and str(outlet_id) != str(actor.outlet_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage staff at your own outlet.",
        )


@router.get("/", response_model=list[UserRead])
async def list_users(
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Staff accounts at the caller's own outlet. Managers and up.

    Previously returned the whole staff table — every account at every
    restaurant — to any authenticated staff member. Two separate limits now
    apply, and both are deliberate:

      * a manager gate, because `username` IS the login identifier in this
        system, so the roster is a list of names to guess passwords against;
        and a waiter has no product reason to read it; and
      * outlet scoping, kept even for callers who pass the gate, so a
        compromised manager account cannot enumerate another restaurant.

    No shipped client calls this route (checked across customer_app, owner_app,
    GustoPOS and GustoWaiter before narrowing it); it is admin tooling.
    """
    _require_manager(actor)
    if is_super_admin(actor):
        return await UserService.get_all_users(db)
    return await UserService.get_users_for_outlet(db, actor.outlet_id)


@router.get("/{item_id}", response_model=UserRead)
async def get_user(
    item_id: UUID,
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    obj = await UserService.get_user_by_id(db, item_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Reading your own account is always allowed; anything else is scoped.
    if str(obj.id) != str(actor.id) and not is_super_admin(actor):
        if actor.outlet_id is None or str(obj.outlet_id) != str(actor.outlet_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="User not found")
    return obj


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate = Body(...),
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Create a staff account.

    A manager may create one only at their OWN outlet and may not grant roles.
    `role_ids: []` is refused for a non-super-admin rather than silently
    accepted: a role-less account was exactly what the old owner-settings
    deny-list mistook for the restaurant's owner, so minting one must be a
    privileged act even now that the gate no longer infers from it.
    """
    _require_manager(actor)
    _require_own_outlet(actor, payload.outlet_id)

    if not is_super_admin(actor):
        # TWO RULES THAT TOGETHER MEAN A MANAGER CANNOT CREATE HERE, and that
        # is the intended outcome rather than an accident of their ordering:
        #
        #   * granting a role is how you escalate, so roles are admin-only;
        #   * a ROLE-LESS account is what the old owner-settings deny-list
        #     mistook for the restaurant's owner, so minting one is admin-only
        #     too — even now the gate no longer infers from an absence,
        #     because re-opening that shape is not worth the convenience.
        #
        # A manager therefore has no legal body for this route. That is fine:
        # POST /staff is the supported way to add staff, it assigns a role via
        # StaffService._ROLE_MAP, and it is what owner_app actually calls. The
        # refusal names it so the caller is not left guessing.
        if payload.role_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a platform admin can set roles on an account.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only a platform admin can create an account without a role. "
                "Use the staff screen to add staff."
            ),
        )

    return await UserService.create_user(db, payload)


@router.put("/{item_id}", response_model=UserRead)
async def update_user(
    item_id: UUID,
    payload: dict[str, Any] = Body(...),
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    """Update a staff account.

    The body is still a free-form dict (that is the existing contract), so the
    privileged fields are filtered explicitly rather than by a schema.
    """
    _require_manager(actor)

    target = await UserService.get_user_by_id(db, item_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_own_outlet(actor, target.outlet_id)

    # NOBODY EDITS THEIR OWN ROLES OR OUTLET — not even a super admin.
    #
    # Those two are self-promotion and self-relocation, and there is no
    # legitimate use for either: another admin can always do it. Refusing them
    # unconditionally means the rule needs no exception to reason about, and it
    # is what stops a waiter promoting themselves even if the role gate above
    # is ever loosened again.
    if str(item_id) == str(actor.id):
        offending = [f for f in _PRIVILEGED_FIELDS if f in payload]
        if offending:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You cannot change your own "
                    + " or ".join(f.replace("_ids", "s").replace("_id", "")
                                  for f in offending)
                    + "."
                ),
            )

    if not is_super_admin(actor):
        for field in _PRIVILEGED_FIELDS:
            if field in payload:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Only a platform admin can change {field}.",
                )
        # is_outlet_owner is the marker the owner gate reads, so handing it out
        # is handing out the gate.
        if "is_outlet_owner" in payload:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only a platform admin can change is_outlet_owner.",
            )

    obj = await UserService.update_user(db, item_id, payload)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    item_id: UUID,
    actor: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
):
    _require_manager(actor)

    target = await UserService.get_user_by_id(db, item_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_own_outlet(actor, target.outlet_id)

    # Deleting yourself is not an escalation, but it is almost certainly a
    # mistake and it locks the outlet out of its own staff management.
    if str(item_id) == str(actor.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot delete your own account.",
        )

    if not await UserService.delete_user(db, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
