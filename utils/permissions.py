from rest_framework.permissions import BasePermission 


class IsSuperUser(BasePermission):
    messge="Access Denied. super user role is required to access!"

    def has_permission(self,request,view):
        return request.user.is_authenticated and request.user.role == "super"


class IsSalesPerson(BasePermission):
    message="Access Denied. Role `Sales` is required"

    def has_permission(self, request, view):
        return super().has_permission(request, view)


class IsStaff(BasePermission):
    message="Access Denied. Role `Staff` is required"

    def has_permission(self, request, view):
        return super().has_permission(request, view)

class IsPM(BasePermission):
    message="Access Denied. Role `Project Manamagement` is required"

    def has_permission(self, request, view):
        return super().has_permission(request, view)