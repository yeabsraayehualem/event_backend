from rest_framework.permissions import BasePermission 


class IsSuperUser(BasePermission):
    messge="Access Denied. super user role is required to access!"

    def has_permission(self,request,view):
        return request.user.is_authenticated and request.user.role == "super"


class IsSalesPerson(BasePermission):
    message="Access Denied. Role `Sales` is required"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "sales"


class IsSalesOrSuper(BasePermission):
    message = "Access denied. Sales or super user role is required."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in {"sales", "super"}


class IsSalesOrFinanceOrSuper(BasePermission):
    message = "Access denied. Sales, finance, or super user role is required."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in {"sales", "finance", "super"}


class IsLeadAssigneeOrSuper(BasePermission):
    message = "Only a super user or the sales person assigned to this lead may access it."

    def has_object_permission(self, request, view, obj):
        return (
            request.user.is_authenticated
            and (
                request.user.role == "super"
                or obj.assigned_sales_person_id == request.user.pk
            )
        )


class IsStaff(BasePermission):
    message="Access Denied. Role `Staff` is required"

    def has_permission(self, request, view):
        return super().has_permission(request, view)

class IsPM(BasePermission):
    message = "Access denied. Project Management access is required."

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in {"pm", "super"}
