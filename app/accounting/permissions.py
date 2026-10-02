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
    """Legacy, role-only gate -- no action/module awareness, kept only for
    the Accounting role-management endpoints themselves (router_roles.py),
    where "who can reassign accounting_role" is deliberately its own
    narrower axis, not something System A's module/action matrix should
    arbitrate. Developer always passes (System A's own top precedence
    rule), same as everywhere else."""
    allowed_set = set(allowed)

    def _dep(
        admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
    ) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        if user and user.role == "developer":
            return "developer"
        role = user.accounting_role if user and user.accounting_role else "Viewer"
        if role not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=f"Your accounting role ({role}) does not permit this action.",
            )
        return role

    return _dep


def require_module_action(module: str, action: str, legacy_roles):
    """Unified action-aware gate -- the one bridge between the legacy
    accounting_role axis and System A's module/action RBAC (app/permissions.py),
    used by Accounting, Delivery and Labour alike (each passes its own
    `module` name and legacy role-set).

    Precedence (mirrors System A's own, documented in app/permissions.py):
      1. Developer -- always allowed, unconditionally. (Previously this
         function denied a developer outright whenever accounting_role was
         unset, which was the actual bug: the site's own superuser account
         could get locked out of Accounting/Delivery/Labour writes.)
      2. If the user has an explicit legacy accounting_role, that role is
         authoritative: allowed only if it's in `legacy_roles`. Nothing is
         converted, so existing Owner/Admin/Accountant/Sales Staff/
         Purchase Staff/Viewer assignments behave exactly as before for
         anyone who already has one set.
      3. Otherwise (no legacy role assigned -- the normal case for a
         regular "admin", "super_access", or "custom" account that was
         never given an accounting_role), defer entirely to System A's
         check_permission(module, action): this applies user-level DENY/
         ALLOW overrides, then the resolved role's RolePermission row
         (custom role, Admin (Default), or Super Access), then default
         deny -- the same engine every other module already uses, so a
         Developer-granted custom-role permission for this module actually
         takes effect instead of being silently ignored.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    allowed_set = set(legacy_roles)

    def _dep(
        admin: str = Depends(get_current_admin), db: Session = Depends(get_db)
    ) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")

        if user.role == "developer":
            return "developer"

        explicit = user.accounting_role if user.accounting_role else None
        if explicit:
            if explicit in allowed_set:
                return explicit
            detail = f"Your accounting role ({explicit}) does not permit this action."
        elif check_permission(db, user, module, action):
            return user.role
        else:
            detail = f"You do not have permission to {action} in {module.capitalize()}."

        record_admin_audit(
            admin, UNAUTHORIZED_ACCESS_ATTEMPT, {"module": module, "action": action}
        )
        raise HTTPException(status_code=403, detail=detail)

    return _dep


def require_accounting_action(action: str, legacy_roles):
    """Accounting-specific convenience wrapper around require_module_action
    -- kept as a separate name since it's already imported this way across
    the Accounting routers; Delivery/Labour call require_module_action
    directly with their own module name instead of needing their own
    identical wrapper."""
    return require_module_action("accounting", action, legacy_roles)