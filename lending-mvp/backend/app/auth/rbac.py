"""
Role-Based Access Control (RBAC) helpers
=========================================
Central module for all permission checks and branch-scoping logic.
Import these helpers in all resolvers instead of duplicating inline checks.

Role hierarchy (most privileged first):
    admin > branch_manager > loan_officer > teller > auditor > customer
"""
from typing import Optional
from fastapi import HTTPException, status
from strawberry.types import Info


# ---------------------------------------------------------------------------
# Canonical role sets
# ---------------------------------------------------------------------------

ALL_STAFF_ROLES = {"admin", "branch_manager", "loan_officer", "teller", "auditor", "collections_officer"}
BRANCH_SCOPED_ROLES = {"branch_manager", "loan_officer", "teller", "collections_officer"}   # see own branch only
CROSS_BRANCH_ROLES = {"admin", "auditor"}                             # see all branches
APPROVAL_ROLES = {"admin", "branch_manager"}                          # approve / disburse
MANAGEMENT_ROLES = {"admin", "branch_manager", "loan_officer"}        # create / edit records

# ---------------------------------------------------------------------------
# Primitive guards
# ---------------------------------------------------------------------------

def require_authenticated(info: Info):
    """Raise 401 if request has no authenticated user."""
    user = info.context.get("current_user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_roles(info: Info, *roles: str):
    """
    Raise 403 unless the authenticated user's role is in *roles*.
    Returns the current_user on success.
    """
    user = require_authenticated(info)
    if user.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Not authorized — required role(s): {', '.join(roles)}",
        )
    return user


def require_any_staff(info: Info):
    """Require any staff role (not customer)."""
    return require_roles(info, *ALL_STAFF_ROLES)


def require_approval_role(info: Info):
    """Only admin and branch_manager may approve or disburse."""
    return require_roles(info, *APPROVAL_ROLES)


def require_management_role(info: Info):
    """Admin, branch_manager, and loan_officer may create / edit records."""
    return require_roles(info, *MANAGEMENT_ROLES)


# ---------------------------------------------------------------------------
# Branch-scoping helpers
# ---------------------------------------------------------------------------

def get_user_branch_code(user) -> Optional[str]:
    """
    Return the branch_code stored on the user object, or None.
    Supports both dict-style and attribute-style user objects.
    """
    if isinstance(user, dict):
        return user.get("branch_code") or user.get("branch")
    return getattr(user, "branch_code", None) or getattr(user, "branch", None)


def get_mongo_branch_filter(user) -> dict:
    """
    Return a MongoDB filter dict that scopes results to the user's branch.
    Returns {} (no filter) for admin and auditor so they see all branches.

    Usage:
        branch_filter = get_mongo_branch_filter(current_user)
        query = {"status": "active", **branch_filter}
        docs = await collection.find(query).to_list()
    """
    if user.role in CROSS_BRANCH_ROLES:
        return {}
    branch_code = get_user_branch_code(user)
    if not branch_code:
        # User has no branch assigned — return only an impossible filter
        # to prevent accidental cross-branch data leakage
        return {"branch_code": "__unassigned__"}
    return {"branch_code": branch_code}


def get_sql_branch_filter(user) -> Optional[str]:
    """
    Return the branch_code to use in a SQLAlchemy WHERE clause,
    or None if the user can see all branches.

    Usage:
        branch_code = get_sql_branch_filter(current_user)
        if branch_code:
            query = query.filter(Model.branch_code == branch_code)
    """
    if user.role in CROSS_BRANCH_ROLES:
        return None
    return get_user_branch_code(user)


def assert_branch_access(user, record_branch_code: Optional[str]):
    """
    Raise 403 if the user is not allowed to access a record belonging to
    *record_branch_code*.  Admin and auditor always pass.
    """
    if user.role in CROSS_BRANCH_ROLES:
        return
    user_branch = get_user_branch_code(user)
    if user_branch and record_branch_code and user_branch != record_branch_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied — record belongs to branch '{record_branch_code}'",
        )


def assert_own_branch_teller(user, requested_branch_code: Optional[str]):
    """
    Specific guard for teller cash-drawer operations.
    A teller must only open/close drawers for their own branch.
    """
    if user.role == "admin":
        return
    user_branch = get_user_branch_code(user)
    if requested_branch_code and user_branch != requested_branch_code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Teller can only operate cash drawers for their own branch ('{user_branch}')",
        )
