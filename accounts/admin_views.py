"""Staff accounts: who can sign in, and with which role. Admins and super users manage them."""

import secrets

from django.contrib.auth import password_validation, update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from chatter.tracking import log_changes, post_message, snapshot
from hr.models import Employee
from utils.permissions import IsUserAdmin
from utils.rbac import access_summary

USER_TRACKED_FIELDS = ["first_name", "last_name", "phone", "email", "role", "is_active"]

# Most access first, for the role picker.
ROLE_ORDER = ["super", "admin", "finance", "sales", "pm", "hr", "stock", "staff"]

# What each role opens in the system. Keep in step with utils/permissions.py.
ROLE_GUIDE = {
    User.Role.SUPER: "Everything, including other super users.",
    User.Role.ADMIN: "Everything except managing super users. Sees every lead and can assign sales people.",
    User.Role.SALES: "Their own leads and customers, and the sales dashboard. Winning a lead hands it to finance and project management.",
    User.Role.FINANCE: "Invoices, expenses and company financials; approves purchase orders and payroll and pays crew.",
    User.Role.PM: "Projects and tasks, vendors and purchase orders, event budgets, and the crew directory and schedule.",
    User.Role.HR: "Crew directory and event schedule, and preparing payroll drafts.",
    User.Role.STOCK: "Vendors and purchase orders. Inventory comes later.",
    User.Role.STAFF: "Can sign in, but no modules yet.",
}


def _temporary_password():
    # 12 characters, no look-alikes, so it can be read out or sent by SMS.
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


def _set_password(user, password):
    """Validate and set `password`, or a generated one. Returns the generated password, if any."""
    generated = None
    if not password:
        password = generated = _temporary_password()
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as error:
        raise ValidationError({"password": list(error.messages)}) from None
    user.set_password(password)
    return generated


class UserAdminSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    employee = serializers.SerializerMethodField()
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), write_only=True, required=False, allow_null=True,
    )
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = [
            "id", "phone", "first_name", "last_name", "full_name", "email", "role", "role_label", "is_active",
            "last_login", "date_joined", "employee", "employee_id", "password",
        ]
        read_only_fields = ["id", "last_login", "date_joined"]

    def get_full_name(self, user):
        return user.get_full_name() or user.phone

    def get_employee(self, user):
        employee = getattr(user, "employee", None)
        return {"id": employee.id, "full_name": employee.full_name} if employee else None

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter the phone number they sign in with.")
        return value

    def validate_employee_id(self, employee):
        if employee and employee.user_id and employee.user_id != getattr(self.instance, "pk", None):
            raise serializers.ValidationError(f"{employee.full_name} is already linked to another account.")
        return employee

    def validate(self, attrs):
        actor = self.context["request"].user
        target = self.instance
        new_role = attrs.get("role", getattr(target, "role", User.Role.STAFF))

        if actor.role != User.Role.SUPER:
            if new_role == User.Role.SUPER:
                raise PermissionDenied("Only a super user can give someone the super user role.")
            if target is not None and target.role == User.Role.SUPER:
                raise PermissionDenied("Only a super user can change another super user.")

        if target is not None and target.pk == actor.pk:
            if "role" in attrs and attrs["role"] != target.role:
                raise ValidationError({"role": "You can't change your own role. Ask another admin."})
            if attrs.get("is_active") is False:
                raise ValidationError({"is_active": "You can't deactivate your own account."})

        if target is not None and target.role == User.Role.SUPER and target.is_active:
            losing = new_role != User.Role.SUPER or attrs.get("is_active") is False
            others = User.objects.filter(role=User.Role.SUPER, is_active=True).exclude(pk=target.pk).exists()
            if losing and not others:
                raise ValidationError({"detail": "This is the last active super user. Make someone else super user first."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        employee = validated_data.pop("employee_id", None)
        password = validated_data.pop("password", "")
        user = User(username=validated_data["phone"], **validated_data)
        self.generated_password = _set_password(user, password)
        user.save()
        self._link(user, employee, linking=employee is not None)
        return user

    @transaction.atomic
    def update(self, user, validated_data):
        linking = "employee_id" in validated_data
        employee = validated_data.pop("employee_id", None)
        validated_data.pop("password", None)  # passwords go through the reset endpoint
        for field, value in validated_data.items():
            setattr(user, field, value)
        if "phone" in validated_data:
            user.username = user.phone
        user.save()
        self._link(user, employee, linking)
        return user

    @staticmethod
    def _link(user, employee, linking):
        if not linking:
            return
        Employee.objects.filter(user=user).exclude(pk=getattr(employee, "pk", None)).update(user=None)
        if employee is not None:
            employee.user = user
            employee.save(update_fields=["user"])


class UserList(ListCreateAPIView):
    """GET staff accounts (?q=, ?role=, ?active=true|false); POST to add one.

    Leave `password` empty to generate a temporary one; it is returned once as `temporary_password`.
    """

    serializer_class = UserAdminSerializer
    permission_classes = [IsUserAdmin]

    def get_queryset(self):
        queryset = User.objects.select_related("employee").order_by("first_name", "last_name", "phone")
        params = self.request.query_params
        if params.get("q"):
            q = params["q"].strip()
            queryset = queryset.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
        if params.get("role"):
            queryset = queryset.filter(role=params["role"])
        if params.get("active") in {"true", "false"}:
            queryset = queryset.filter(is_active=params["active"] == "true")
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        post_message(user, body=f"Account created with the {user.get_role_display()} role.", author=request.user)
        data = self.get_serializer(user).data
        if getattr(serializer, "generated_password", None):
            data["temporary_password"] = serializer.generated_password
        return Response(data, status=201)


class UserDetail(RetrieveUpdateAPIView):
    serializer_class = UserAdminSerializer
    permission_classes = [IsUserAdmin]
    queryset = User.objects.select_related("employee")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, USER_TRACKED_FIELDS)
        user = serializer.save()
        log_changes(user, before, USER_TRACKED_FIELDS, self.request.user, labels={"is_active": "Active", "role": "Role"})


class UserPasswordReset(APIView):
    """POST {"password"?} to set someone's password. Empty generates a temporary one, returned once."""

    permission_classes = [IsUserAdmin]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.role == User.Role.SUPER and request.user.role != User.Role.SUPER:
            raise PermissionDenied("Only a super user can reset another super user's password.")
        generated = _set_password(user, str(request.data.get("password", "")))
        user.save(update_fields=["password"])  # also signs them out everywhere else
        post_message(user, body="Password reset.", author=request.user)
        return Response({"temporary_password": generated} if generated else {"detail": "Password updated."})


class UserOptions(APIView):
    permission_classes = [IsUserAdmin]

    def get(self, request):
        counts = dict(User.objects.filter(is_active=True).values_list("role").annotate(n=Count("id")))
        roles = [
            {"value": value, "label": label, "description": ROLE_GUIDE.get(value, ""), "active_count": counts.get(value, 0),
             "access": access_summary(value)}
            for value, label in sorted(User.Role.choices, key=lambda choice: ROLE_ORDER.index(choice[0]))
            if value != User.Role.SUPER or request.user.role == User.Role.SUPER
        ]
        employees = Employee.objects.filter(active=True).order_by("full_name")
        return Response({
            "roles": roles,
            "employees": [{"id": e.id, "full_name": e.full_name, "phone": e.phone, "user_id": e.user_id} for e in employees],
            "me": request.user.pk,
            "is_super": request.user.role == User.Role.SUPER,
        })


class ChangeOwnPassword(APIView):
    """POST {"current_password", "new_password"}: any signed-in user changing their own password."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.check_password(str(request.data.get("current_password", ""))):
            raise ValidationError({"current_password": "That isn't your current password."})
        new_password = str(request.data.get("new_password", ""))
        if not new_password:
            raise ValidationError({"new_password": "Enter a new password."})
        _set_password(user, new_password)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)  # stay signed in here
        return Response({"detail": "Password changed."})
