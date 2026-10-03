"""Accounting/Delivery/Labour write-action gate.

Used to be a second, independent "accounting_role" axis (Owner/Admin/
Accountant/Sales Staff/Purchase Staff/Viewer) layered on top of the
module/action RBAC matrix (app/permissions.py, "Roles & Permissions").
That legacy axis has been retired -- every write action in these three
modules is now gated purely by the tick-based Roles & Permissions matrix,
same as every other module in the app. `legacy_roles` arguments below are
kept only so the ~20 existing call sites across Accounting/Delivery/Labour
routers don't all need editing; they're no longer read for anything.

Read (GET) endpoints stay open to any logged-in admin, same as before.
Only mutating endpoints (POST/PUT/DELETE/void/convert) gate on permission.
"""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import UNAUTHORIZED_ACCESS_ATTEMPT, record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.models import AdminUser
from app.permissions import ACTIONS, check_permission

# Resource-group role matrices -- unused now that the legacy accounting_role
# axis is retired; kept only because require_module_action's call sites
# still pass them positionally.
SALES_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Sales Staff"}
PURCHASE_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Purchase Staff"}
CONTACT_WRITE_ROLES = {"Owner", "Admin", "Accountant", "Sales Staff", "Purchase Staff"}
SETTINGS_WRITE_ROLES = {"Owner", "Admin", "Accountant"}  # Chart of Accounts, Tax Rates
EMPLOYEE_WRITE_ROLES = {"Owner", "Admin"}


def require_module_action(module: str, action: str, legacy_roles=None):
    """Action-aware gate: Developer always passes; everyone else is
    checked against System A's check_permission(module, action) -- user
    overrides, then the resolved role's RolePermission row, then default
    deny. `legacy_roles` is accepted for call-site compatibility and
    ignored."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")

    def _dep(
        admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
    ) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        if user.role == "developer":
            return "developer"

        if check_permission(db, user, module, action):
            return user.role

        record_admin_audit(
            admin, UNAUTHORIZED_ACCESS_ATTEMPT, {"module": module, "action": action}
        )
        raise HTTPException(
            status_code=403, detail=f"You do not have permission to {action} in {module.capitalize()}."
        )

    return _dep


def require_accounting_action(action: str, legacy_roles=None):
    """Accounting-specific convenience wrapper around require_module_action
    -- kept as a separate name since it's already imported this way across
    the Accounting routers; Delivery/Labour call require_module_action
    directly with their own module name instead of needing their own
    identical wrapper."""
    return require_module_action("accounting", action, legacy_roles)