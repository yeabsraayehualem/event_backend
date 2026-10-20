from rest_framework import serializers

from crm.models import Customers, Lead
from event.models import Package, Plan
from website.serializers import PackageSerializer

class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model= Customers
        fields = ["id","name","phone"]




class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model= Plan
        fields = ["id","name"]

class LeadsSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(many=False)
    plan = PlanSerializer(many=False)
    package = PackageSerializer(many=False, read_only=True, allow_null=True)
    class Meta:
        model= Lead
        fields= ["id", "customer", "plan", "package", "plan_date", "date", "location", "status", "notes"]
