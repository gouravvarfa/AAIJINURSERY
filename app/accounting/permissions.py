"""Accounting module role-based permissions (Phase 4).

This is a second, independent permission axis from AdminUser.role (which
only governs Website Management / developer access) -- an admin's
accounting_role decides what they can do *inside* Accounting only.

Read (GET) endpoints stay open to any logged-in admin, same as before --
"Viewer" is exactly that: full read access, no writes. Only mutating
endpoints (POST/PUT/DELETE/void/convert) gate on role.
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import UNAUTHORIZED_ACCESS_ATTEMPT, record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.models import AdminUser
from app.permissions import ACTIONS, check_permission

ROLES = ["Owner", "Admin", "Accountant", "Sales Staff", "Purchase Staff", "Viewer"]

# Resource-group role matrices -- a set of roles allowed to WRITE to that group.
SALES_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Sales Staff"}
PURCHASE_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Purchase Staff"}
CONTACT_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Sales Staff", "Purchase Staff"}
SETTINGS_WRITE_ROLES = {"Owner", "Admin", "Accountant"}  # Chart of Accounts, Tax Rates
EMPLOYEE_WRITE_ROLES = {"Owner", "Admin"}
ROLE_MANAGEMENT_ROLES = {"Owner"}


def get_accounting_role(
    admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
) -> str:
    user = db.query(AdminUser).filter(AdminUser.username == admin).first()
    return (user.accounting_role if user and user.accounting_role else "Viewer")


def require_roles(*allowed: str):
    allowed_set = set(allowed)

    def _dep(role: str = Depends(get_accounting_role)) -> str:
        if role not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=f"Your accounting role ({role}) does not permit this action.",
            )
        return role

    return _dep


def require_accounting_action(action: str, legacy_roles):
    """Action-aware gate for Accounting writes (bridges the two RBAC axes).

    Precedence:
      1. Authentication (get_current_admin -> 401 if missing).
      2. Module VIEW boundary is enforced separately at the router mount
         in main.py (require_permission("accounting", "VIEW")).
      3. If the user has an explicit accounting_role, that legacy role is
         authoritative: allowed only if it is in `legacy_roles`. Nothing is
         converted, so existing Owner/Admin/Accountant/Sales Staff/
         Purchase Staff/Viewer behavior is unchanged. (Known limitation: an
         explicit legacy role is NOT overridden by a module-matrix DENY.)
      4. Otherwise, for role == "custom", defer to app.permissions.
         check_permission(), which already applies user DENY/ALLOW
         overrides, then the custom role's RolePermission row, then
         default deny.
      5. Any other user with no accounting_role keeps the old behavior
         (treated as Viewer -> denied), so access is never widened silently.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    allowed_set = set(legacy_roles)

    def _dep(
        admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
    ) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        explicit = user.accounting_role if user and user.accounting_role else None

        if explicit:
            if explicit in allowed_set:
                return explicit
            detail = f"Your accounting role ({explicit}) does not permit this action."
        elif user and user.role == "custom" and check_permission(db, user, "accounting", action):
            return "custom"
        else:
            detail = f"You do not have permission to {action} in the Accounting module."

        record_admin_audit(
            admin, UNAUTHORIZED_ACCESS_ATTEMPT, {"module": "accounting", "action": action}
        )
        raise HTTPException(status_code=403, detail=detail)

    return _dep