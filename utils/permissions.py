"""DRF permission classes. Every role list comes from utils/rbac.py, the single access table.

The class names are kept so views read naturally; change who may do what in rbac.MODULES.
"""

from rest_framework.permissions import BasePermission

from utils.rbac import action_permission, can, module_permission

# Leads, the sales pipeline and customers.
IsSalesOrSuper = module_permission("leads", message="Access denied. Your role doesn't include leads.")
# Invoices.
IsSalesOrFinanceOrSuper = module_permission("invoices", message="Access denied. Your role doesn't include invoices.")
# Event pickers shared by projects, invoices and procurement.
IsEventStaff = module_permission("events", message="Access denied. Your role doesn't include events.")
# Projects and tasks.
IsPM = module_permission("projects", message="Access denied. Project management access is required.")
# Plans, packages and services: wide read, managers write.
CatalogPermission = module_permission("catalog", message="Only a super user or admin can change the catalog.")
# Vendors and purchase orders.
ProcurementPermission = module_permission("purchase_orders", message="Access denied. Procurement access is required.")
# Expenses.
IsFinance = module_permission("expenses", message="Access denied. Finance access is required.")
# Crew directory and event schedule.
HRPermission = module_permission("crew", message="Access denied. HR or event management access is required.")
# Paying a worked shift.
CanPayCrew = action_permission("crew", "pay", message="Only finance, admins or super users can pay crew.")
# Payroll runs.
PayrollPermission = module_permission("payroll", message="Access denied. Payroll is limited to HR, finance, admins and super users.")
# User accounts.
IsUserAdmin = module_permission("users", message="Only admins and super users can manage user accounts.")
# Merging customer records and other pipeline-wide actions.
CanManageLeads = action_permission("leads", "manage", message="Only admins and super users can do this.")


class IsSuperUser(BasePermission):
    message = "Access denied. Super user role is required."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "super"


class IsLeadAssigneeOrSuper(BasePermission):
    message = "Only the sales person assigned to this lead, an admin or a super user may access it."

    def has_object_permission(self, request, view, obj):
        return can(request.user, "leads", "manage") or obj.assigned_sales_person_id == request.user.pk


def can_manage_leads(user):
    return can(user, "leads", "manage")


def can_approve_purchases(user):
    return can(user, "purchase_orders", "approve")


def can_set_event_budget(user):
    return can(user, "purchase_orders", "budget")


def can_approve_payouts(user):
    return can(user, "crew", "pay")


def can_approve_payroll(user):
    return can(user, "payroll", "approve")
