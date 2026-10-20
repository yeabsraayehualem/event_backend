from decimal import MAX_EMAX
from pickletools import read_long1

from rest_framework import serializers

from event.models import Package, Plan,Content
from .models import ShowcaseEntry


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
    email = serializers.EmailField()
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.all())
    package = serializers.PrimaryKeyRelatedField(
        queryset=Package.objects.all(), required=False, allow_null=True
    )
    plan_date = serializers.DateField()
    location = serializers.CharField(max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True)
    event_type = serializers.CharField(max_length=120, required=False, allow_blank=True)
    guest_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    budget_tier = serializers.CharField(max_length=80, required=False, allow_blank=True)
    requirements = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        package = attrs.get("package")
        if package and package.plan_id != attrs["plan"].id:
            raise serializers.ValidationError({"package": "Choose a package from the selected plan."})
        return attrs


class ShowcaseSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ShowcaseEntry
        fields = ["id", "kind", "title", "description", "image_url", "attribution", "position"]

    def get_image_url(self, entry):
        request = self.context.get("request")
        if not entry.image:
            return None
        return request.build_absolute_uri(entry.image.url) if request else entry.image.url
