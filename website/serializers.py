from rest_framework import serializers

from event.models import Content, EventType, Package, Plan
from .models import ShowcaseEntry


class ContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Content
        fields = ["id","name","description"]


class PackageSerializer(serializers.ModelSerializer):
    contents = ContentSerializer(many=True,read_only=True)
    class Meta:
        model = Package
        fields = ["id", "name", "description", "price", "contents"]


class EventTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventType
        fields = ["id", "name"]


class GetPlans(serializers.ModelSerializer):
    packages = serializers.SerializerMethodField()
    event_types = EventTypeSerializer(many=True, read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = ["id", "name", "description", "image", "packages", "event_types"]

    def get_image(self, plan):
        if not plan.image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(plan.image.url) if request else plan.image.url

    def get_packages(self, plan):
        # Cheapest first, so the website can say "from ETB …".
        packages = sorted(plan.packages.all(), key=lambda package: (package.price <= 0, package.price, package.id))
        return PackageSerializer(packages, many=True, context=self.context).data



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
    event_type = serializers.PrimaryKeyRelatedField(
        queryset=EventType.objects.all(), required=False, allow_null=True,
    )
    guest_count = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    budget_tier = serializers.CharField(max_length=80, required=False, allow_blank=True)
    requirements = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        package = attrs.get("package")
        if package and package.plan_id != attrs["plan"].id:
            raise serializers.ValidationError({"package": "Choose a package from the selected plan."})
        event_type = attrs.get("event_type")
        if event_type and event_type.plan_id != attrs["plan"].id:
            raise serializers.ValidationError({"event_type": "Choose an occasion from the selected plan."})
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
