from rest_framework import serializers
from django.contrib.auth import get_user_model

from crm.models import Customers, Lead
from event.models import Package, Plan
from website.serializers import PackageSerializer

User = get_user_model()

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model= Customers
        fields = ["id","name","phone"]




class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model= Plan
        fields = ["id","name"]


class LeadPlanDetailSerializer(serializers.ModelSerializer):
    packages = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ["id", "name", "packages"]

    def get_packages(self, plan):
        return [{"id": package.id, "name": package.name} for package in plan.packages.all()]

class LeadsSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(many=False)
    plan = PlanSerializer(many=False)
    package = PackageSerializer(many=False, read_only=True, allow_null=True)
    class Meta:
        model= Lead
        fields= ["id", "customer", "plan", "package", "plan_date", "date", "location", "status", "notes"]


class LeadDetailSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    plan = LeadPlanDetailSerializer(read_only=True)
    package = PackageSerializer(read_only=True, allow_null=True)
    package_id = serializers.PrimaryKeyRelatedField(
        source="package", queryset=Package.objects.all(), required=False,
        allow_null=True, write_only=True,
    )
    assigned_sales_person = serializers.StringRelatedField(allow_null=True, read_only=True)
    assigned_sales_person_id = serializers.PrimaryKeyRelatedField(
        source="assigned_sales_person",
        queryset=User.objects.filter(role=User.Role.SALES),
        required=False,
        allow_null=True,
    )
    can_assign_sales = serializers.SerializerMethodField()
    available_sales_people = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id", "customer", "plan", "package", "date", "plan_date",
            "package_id", "location", "status", "status_label", "notes",
            "assigned_sales_person", "assigned_sales_person_id", "can_assign_sales",
            "available_sales_people",
        ]

    def get_can_assign_sales(self, _lead):
        request = self.context.get("request")
        return bool(request and request.user.role == User.Role.SUPER)

    def get_available_sales_people(self, _lead):
        request = self.context.get("request")
        if not request or request.user.role != User.Role.SUPER:
            return []
        return [
            {"id": person.id, "name": person.get_full_name() or person.phone}
            for person in User.objects.filter(role=User.Role.SALES).order_by(
                "first_name", "last_name", "phone"
            )
        ]

    def validate_assigned_sales_person_id(self, _value):
        request = self.context.get("request")
        if not request or request.user.role != User.Role.SUPER:
            raise serializers.ValidationError("Only a super user can assign a sales person.")
        return _value

    def validate(self, attrs):
        package = attrs.get("package")
        if package is not None and package.plan_id != self.instance.plan_id:
            raise serializers.ValidationError({
                "package_id": "Choose a package that belongs to this lead's plan."
            })
        return attrs
