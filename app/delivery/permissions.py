"""Reuses the same accounting_role axis via require_module_action() --
also bridges to System A's module/action RBAC (app/permissions.py,
module="delivery") so a Developer-granted custom-role permission for
Delivery actually takes effect, instead of only the legacy accounting_role
tier (Owner/Admin/Accountant) ever working. See require_module_action's
docstring in app/accounting/permissions.py for the exact precedence.
Driver Portal auth (Phase C) is separate."""
from app.accounting.permissions import require_module_action

DELIVERY_WRITE_ROLES = {"Owner", "Admin", "Accountant"}


def require_roles(action: str):
    """Delivery's own thin wrapper -- fixes `module="delivery"` so call
    sites only need to name the action, same call shape as before
    (`require_roles(ACTION)` instead of the old `require_roles(*ROLES)`)."""
    return require_module_action("delivery", action, DELIVERY_WRITE_ROLES)
