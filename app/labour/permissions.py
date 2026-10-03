"""Reuses the same accounting_role axis via require_module_action() -- also
bridges to System A's module/action RBAC (app/permissions.py, module=
"labour") so a Developer-granted custom-role permission for Labour actually
takes effect, instead of only the legacy accounting_role tier ever working.
See require_module_action's docstring in app/accounting/permissions.py for
the exact precedence."""
from app.accounting.permissions import require_module_action

# Payroll/attendance/advances/payments are gated to the same financial
# roles as Accounting's purchase-side writes -- Sales/Purchase Staff don't
# get labour-management access by default.
LABOUR_WRITE_ROLES = {"Owner", "Admin", "Accountant"}


def require_roles(action: str):
    """Labour's own thin wrapper -- fixes `module="labour"` so call sites
    only need to name the action."""
    return require_module_action("labour", action, LABOUR_WRITE_ROLES)
