from decimal import MAX_EMAX
from pickletools import read_long1

from rest_framework import serializers

from event.models import Package, Plan,Content


class ContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Content
        fields = ["id","name","description"]


class PackageSerializer(serializers.ModelSerializer):
    contents = ContentSerializer(many=True,read_only=True)
    class Meta:
        model = Package
        fields = ["id", "name","contents"] 


class GetPlans(serializers.ModelSerializer):
    packages = PackageSerializer(many=True, read_only=True)

    class Meta:
        model = Plan
        fields = ["id", "name", "packages"]



class PublicLeadSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True)
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    package = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.all(), required=False, allow_null=True
    )
    plan_date = serializers.DateField()
    location = serializers.CharField(max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        package = attrs.get("package")
        if package and package.plan_id != attrs["plan"].id:
            raise serializers.ValidationError({"package": "Choose a package from the selected plan."})
        return attrs
