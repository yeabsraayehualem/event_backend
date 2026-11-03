"""Role-based access control: one table of which role may do what, used by every API check.

`MATRIX[module][action]` is the set of roles allowed. Actions:

* view    – open the module and read its records
* create  – add records
* edit    – change or delete records
* approve – sign off (purchase orders, payroll); module-specific extras are named below

The same table is sent to the frontend (see `permissions_for`) so menus, pages and buttons
match what the API will allow. Change access here, not in individual views.

Super users can do everything. Admins can do everything except manage super users
(that rule lives in accounts/admin_views.py).
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

SUPER, ADMIN = "super", "admin"
SALES, FINANCE, PM, HR, STOCK, STAFF = "sales", "finance", "pm", "hr", "stock", "staff"
MANAGERS = {SUPER, ADMIN}


def _all(*roles):
    return set(roles) | MANAGERS


MODULES = {
    # Home page. Each section on it is gated by its own module below. HR and stock have no
    # dashboard sections, so they land on their own module instead.
    "dashboard": {"label": "Dashboard", "view": _all(SALES, FINANCE, PM)},
    # Company-wide income, expense and net gain on the dashboard.
    "financials": {"label": "Company financials", "view": _all(FINANCE)},
    # `manage`: see every lead (not just your own), assign sales people, merge customers.
    "leads": {"label": "Leads & customers", "view": _all(SALES), "create": _all(SALES), "edit": _all(SALES), "manage": _all()},
    # Event records created from won leads; used as pickers across modules.
    "events": {"label": "Events", "view": _all(FINANCE, PM)},
    # Sales only work leads: winning one creates the deposit invoice automatically, and finance takes it from there.
    "invoices": {"label": "Invoices", "view": _all(FINANCE), "create": _all(FINANCE), "edit": _all(FINANCE)},
    "expenses": {"label": "Expenses", "view": _all(FINANCE), "create": _all(FINANCE), "edit": _all(FINANCE)},
    "projects": {"label": "Projects & tasks", "view": _all(PM), "create": _all(PM), "edit": _all(PM)},
    # The lead form gets its plan and package choices from the leads API, so sales don't need this.
    "catalog": {"label": "Catalog", "view": _all(FINANCE, PM), "create": _all(), "edit": _all()},
    "vendors": {"label": "Vendors", "view": _all(PM, FINANCE, STOCK), "create": _all(PM, FINANCE, STOCK), "edit": _all(PM, FINANCE, STOCK)},
    # `budget`: set an event's cost budget.
    "purchase_orders": {
        "label": "Purchase orders", "view": _all(PM, FINANCE, STOCK), "create": _all(PM, FINANCE, STOCK),
        "edit": _all(PM, FINANCE, STOCK), "approve": _all(FINANCE), "budget": _all(PM, FINANCE),
    },
    # Directory and event schedule. `pay`: pay a worked shift.
    "crew": {"label": "Crew", "view": _all(HR, PM, FINANCE), "create": _all(HR, PM), "edit": _all(HR, PM), "pay": _all(FINANCE)},
    # HR prepares drafts; finance approves, pays and sets the tax rules.
    "payroll": {"label": "Payroll", "view": _all(HR, FINANCE), "create": _all(HR, FINANCE), "edit": _all(HR, FINANCE), "approve": _all(FINANCE)},
    "users": {"label": "Users", "view": _all(), "create": _all(), "edit": _all()},
}

METHOD_ACTIONS = {"POST": "create", "PUT": "edit", "PATCH": "edit", "DELETE": "edit"}


def role_of(user):
    return getattr(user, "role", None) if getattr(user, "is_authenticated", False) else None


def can(user, module, action="view"):
    """True when `user`'s role may perform `action` in `module`."""
    role = role_of(user)
    if role is None:
        return False
    if role == SUPER:
        return True
    return role in MODULES[module].get(action, set())


def permissions_for(user):
    """{module: [actions]} the user may perform, for the frontend."""
    return permissions_for_role(role_of(user))


def permissions_for_role(role):
    if role is None:
        return {}
    granted = {}
    for module, rules in MODULES.items():
        actions = [action for action, roles in rules.items() if action != "label" and (role == SUPER or role in roles)]
        if actions:
            granted[module] = actions
    return granted


def access_summary(role):
    """Readable list of what a role opens, e.g. [{"module": "Payroll", "actions": ["view", "create", "edit"]}]."""
    return [
        {"module": MODULES[module]["label"], "actions": actions}
        for module, actions in permissions_for_role(role).items()
    ]


def matrix():
    """The whole table, for documentation and the users page."""
    return {
        module: {"label": rules["label"], **{action: sorted(roles) for action, roles in rules.items() if action != "label"}}
        for module, rules in MODULES.items()
    }


def module_permission(module, read_action="view", message=None):
    """A DRF permission class for `module`: reads need `read_action`, writes need create/edit."""

    class ModulePermission(BasePermission):
        def has_permission(self, request, view):
            action = read_action if request.method in SAFE_METHODS else METHOD_ACTIONS.get(request.method, "edit")
            return can(request.user, module, action)

    ModulePermission.message = message or f"Your role doesn't have access to {MODULES[module]['label'].lower()}."
    ModulePermission.__name__ = f"{module.title().replace('_', '')}Permission"
    return ModulePermission


def action_permission(module, action, message=None):
    """A DRF permission class requiring one specific action, whatever the HTTP method."""

    class ActionPermission(BasePermission):
        def has_permission(self, request, view):
            return can(request.user, module, action)

    ActionPermission.message = message or f"Your role can't do that in {MODULES[module]['label'].lower()}."
    return ActionPermission
