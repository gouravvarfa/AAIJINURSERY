"""Developer Dashboard RBAC: module-level permission engine.

This is a SECOND permission axis layered ON TOP OF -- never a replacement
for -- the existing `accounting_role` axis in app/accounting/permissions.py
(reused as-is by Delivery/Labour). That axis keeps governing fine-grained
writes *inside* Accounting/Delivery/Labour exactly as before. This axis
governs whether an admin can enter a MODULE at all, and what outer-boundary
actions (VIEW/CREATE/EDIT/DELETE/EXPORT/PRINT/APPROVE/CANCEL) they have
there -- same shape as require_roles() in that file, just not
accounting-specific.

Precedence (highest to lowest):
  1. Developer -- system rule, always true, unconditional.
  2. Super Access -- hardcoded floor: never true for the two Developer-only
     technical modules (users_roles, system_health), no matter what a role
     or override says -- this is the actual enforcement of "Super Access
     cannot reach Developer territory," not just a hidden nav item.
  3. A user-level explicit DENY override -- takes something away.
  4. A user-level explicit ALLOW override -- grants something extra.
  5. The admin's role's RolePermission row for that module.
  6. Default deny.
"""

from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import UNAUTHORIZED_ACCESS_ATTEMPT, record_admin_audit
from app.database import get_db
from app.deps import get_current_admin
from app.models import AdminUser, Role, RolePermission, UserPermissionOverride

# Fixed module catalog (spec section 10/37). Some (e.g. "inventory") have no
# enforced endpoints yet -- they still appear in the permission matrix so a
# Developer can pre-configure a custom role ahead of that module shipping.
MODULES = [
    "website",
    "products",
    "orders",
    "customers",
    "analytics",
    "accounting",
    "delivery",
    "labour",
    "communications",
    "inventory",
    "reports",
    "ai_assistant",
    "users_roles",
    "system_health",
]

ACTIONS = ["VIEW", "CREATE", "EDIT", "DELETE", "EXPORT", "PRINT", "APPROVE", "CANCEL"]

# Developer-only technical modules -- Super Access can never reach these,
# regardless of role matrix or per-user override (spec sections 6/7/27/33).
DEVELOPER_ONLY_MODULES = {"users_roles", "system_health"}

ADMIN_DEFAULT_ROLE_NAME = "Admin (Default)"
SUPER_ACCESS_ROLE_NAME = "Super Access"


def _active_overrides(db: Session, admin_user_id: int, module: str, action: str) -> list[UserPermissionOverride]:
    now = datetime.utcnow()
    query = db.query(UserPermissionOverride).filter(
        UserPermissionOverride.admin_user_id == admin_user_id,
        UserPermissionOverride.module == module,
        UserPermissionOverride.action == action,
    )
    return [o for o in query.all() if o.expires_at is None or o.expires_at > now]


def _resolve_role(db: Session, user: AdminUser) -> Role | None:
    if user.role == "custom":
        return db.query(Role).filter(Role.id == user.custom_role_id).first() if user.custom_role_id else None
    if user.role == "admin":
        return db.query(Role).filter(Role.name == ADMIN_DEFAULT_ROLE_NAME).first()
    if user.role == "super_access":
        return db.query(Role).filter(Role.name == SUPER_ACCESS_ROLE_NAME).first()
    return None


def check_permission(db: Session, user: AdminUser, module: str, action: str) -> bool:
    if user.role == "developer":
        return True
    if user.role == "super_access" and module in DEVELOPER_ONLY_MODULES:
        return False

    overrides = _active_overrides(db, user.id, module, action)
    if any(o.effect == "DENY" for o in overrides):
        return False
    if any(o.effect == "ALLOW" for o in overrides):
        return True

    role = _resolve_role(db, user)
    if not role:
        return False
    rp = db.query(RolePermission).filter(RolePermission.role_id == role.id, RolePermission.module == module).first()
    if not rp:
        return False
    return bool(getattr(rp, f"can_{action.lower()}", False))


def get_permissions_map(db: Session, user: AdminUser) -> dict[str, dict[str, bool]]:
    """Every module x action flag for this admin -- used by /auth/me and
    /auth/login so the frontend can build its sidebar and route guards
    without a permission check per nav item."""
    return {module: {action: check_permission(db, user, module, action) for action in ACTIONS} for module in MODULES}


def require_permission(module: str, action: str):
    if module not in MODULES:
        raise ValueError(f"Unknown module: {module}")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")

    def _dep(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)) -> str:
        user = db.query(AdminUser).filter(AdminUser.username == admin).first()
        if not user or not check_permission(db, user, module, action):
            record_admin_audit(admin, UNAUTHORIZED_ACCESS_ATTEMPT, {"module": module, "action": action})
            raise HTTPException(status_code=403, detail="Access Denied")
        return admin

    return _dep
