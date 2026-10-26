from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import transaction

from crm.models import Customers, Lead
from event.models import Package, Plan
from website.serializers import PackageSerializer

User = get_user_model()


class NewSerializer:
    def printer(self):
        print("nothing")

        print("another one")
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
    event_id = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id", "customer", "plan", "package", "date", "plan_date",
            "package_id", "location", "status", "status_label", "notes",
            "event_type", "guest_count", "budget_tier", "requirements",
            "assigned_sales_person", "assigned_sales_person_id", "can_assign_sales",
            "available_sales_people",
            "event_id",
        ]

    def get_event_id(self, lead):
        event_record = getattr(lead, "event_record", None)
        return event_record.id if event_record else None

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


class CRMLeadCreateSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True)
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    package_id = serializers.PrimaryKeyRelatedField(
        source="package", queryset=Package.objects.all(), required=False,
        allow_null=True,
    )
    plan_date = serializers.DateField()
    location = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=Lead.Status.choices, required=False, default=Lead.Status.LEAD)
    event_type = serializers.CharField(max_length=120, required=False, allow_blank=True)
    guest_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    budget_tier = serializers.CharField(max_length=80, required=False, allow_blank=True)
    requirements = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    assigned_sales_person_id = serializers.PrimaryKeyRelatedField(
        source="assigned_sales_person",
        queryset=User.objects.filter(role=User.Role.SALES),
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        package = attrs.get("package")
        if package and package.plan_id != attrs["plan"].id:
            raise serializers.ValidationError({"package_id": "Choose a package from the selected plan."})
        request = self.context.get("request")
        if attrs.get("assigned_sales_person") and (not request or request.user.role != User.Role.SUPER):
            raise serializers.ValidationError({"assigned_sales_person_id": "Only a super user can assign another sales person."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        customer_name = validated_data.pop("customer_name")
        phone = validated_data.pop("phone")
        email = validated_data.pop("email", "")
        customer = Customers.objects.filter(phone=phone).order_by("id").first()
        if customer is None:
            customer = Customers.objects.create(
                phone=phone, name=customer_name, email=email or None,
            )
        elif email and not customer.email:
            customer.email = email
            customer.save(update_fields=["email"])

        if request.user.role == User.Role.SALES:
            validated_data["assigned_sales_person"] = request.user
        lead = Lead.objects.create(customer=customer, **validated_data)
        return lead
