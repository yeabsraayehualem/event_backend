from rest_framework import serializers

from event.models import Package, Plan


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
