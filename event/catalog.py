"""Catalog management: plans (with their event types), packages, and the services they include."""

from django.db import transaction
from django.db.models import Count
from rest_framework import serializers
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView, get_object_or_404
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from chatter.tracking import log_changes, post_message, snapshot
from event.models import Content, EventType, Package, Plan
from utils.permissions import CatalogPermission

PLAN_TRACKED_FIELDS = ["name", "description"]
PACKAGE_TRACKED_FIELDS = ["name", "plan", "price", "description", "contents"]
PACKAGE_FIELD_LABELS = {"contents": "Included services"}


def image_url(request, plan):
    if not plan.image:
        return None
    return request.build_absolute_uri(plan.image.url) if request else plan.image.url


class EventTypeInputSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    name = serializers.CharField(max_length=120, trim_whitespace=True)


class PlanCatalogSerializer(serializers.ModelSerializer):
    event_types = EventTypeInputSerializer(many=True, required=False)
    image_url = serializers.SerializerMethodField()
    packages = serializers.SerializerMethodField()
    lead_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Plan
        fields = ["id", "name", "description", "image_url", "event_types", "packages", "lead_count"]

    def to_representation(self, plan):
        data = super().to_representation(plan)
        data["event_types"] = [
            {"id": item.id, "name": item.name, "lead_count": item.leads.count()}
            for item in plan.event_types.all()
        ]
        return data

    def get_image_url(self, plan):
        return image_url(self.context.get("request"), plan)

    def get_packages(self, plan):
        return [
            {"id": package.id, "name": package.name, "price": str(package.price), "content_count": package.contents.count()}
            for package in plan.packages.order_by("price", "id")
        ]

    def validate_event_types(self, items):
        names = [item["name"].casefold() for item in items]
        duplicates = {item["name"] for item in items if names.count(item["name"].casefold()) > 1}
        if duplicates:
            raise serializers.ValidationError(f"Each event type can only be listed once: {', '.join(sorted(duplicates))}.")
        return items

    @transaction.atomic
    def create(self, validated_data):
        event_types = validated_data.pop("event_types", [])
        plan = Plan.objects.create(**validated_data)
        self.sync_event_types(plan, event_types)
        return plan

    @transaction.atomic
    def update(self, plan, validated_data):
        event_types = validated_data.pop("event_types", None)
        for field, value in validated_data.items():
            setattr(plan, field, value)
        plan.save()
        if event_types is not None:
            self.changes = self.sync_event_types(plan, event_types)
        return plan

    @staticmethod
    def sync_event_types(plan, items):
        """Make the plan's event types match `items` (in order). Returns a readable change list."""
        existing = {item.id: item for item in plan.event_types.all()}
        keep, changes = set(), []
        for position, item in enumerate(items):
            current = existing.get(item.get("id"))
            if current is None:
                EventType.objects.create(plan=plan, name=item["name"], sequence=position)
                changes.append(f"added “{item['name']}”")
                continue
            keep.add(current.id)
            if current.name != item["name"]:
                changes.append(f"renamed “{current.name}” to “{item['name']}”")
            current.name, current.sequence = item["name"], position
            current.save(update_fields=["name", "sequence"])
        for removed in (item for item_id, item in existing.items() if item_id not in keep):
            in_use = removed.leads.count()
            if in_use:
                raise serializers.ValidationError({
                    "event_types": f"“{removed.name}” is used by {in_use} lead{'s' if in_use != 1 else ''}, so it can't be removed. Rename it instead.",
                })
            removed.delete()
            changes.append(f"removed “{removed.name}”")
        return changes


class PackageCatalogSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    content_ids = serializers.PrimaryKeyRelatedField(source="contents", queryset=Content.objects.all(), many=True, required=False)
    contents = serializers.SerializerMethodField()
    lead_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Package
        fields = ["id", "plan", "plan_name", "name", "description", "price", "content_ids", "contents", "lead_count"]

    def get_contents(self, package):
        return [{"id": content.id, "name": content.name} for content in package.contents.order_by("name")]

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("The price can't be negative.")
        return value


class ContentCatalogSerializer(serializers.ModelSerializer):
    package_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Content
        fields = ["id", "name", "description", "package_count"]


class PlanList(ListCreateAPIView):
    serializer_class = PlanCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        return Plan.objects.annotate(lead_count=Count("leads", distinct=True)).prefetch_related("event_types", "packages").order_by("name")

    def perform_create(self, serializer):
        plan = serializer.save()
        post_message(plan, body="Plan created.", author=self.request.user)


class PlanDetail(RetrieveUpdateAPIView):
    serializer_class = PlanCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        return PlanList.get_queryset(self)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, PLAN_TRACKED_FIELDS)
        plan = serializer.save()
        changes = getattr(serializer, "changes", [])
        body = f"Event types: {'; '.join(changes)}." if changes else ""
        if not log_changes(plan, before, PLAN_TRACKED_FIELDS, self.request.user, body=body) and body:
            post_message(plan, body=body, author=self.request.user)


class PlanImage(APIView):
    """Upload (POST, multipart `image`) or remove (DELETE) a plan's picture."""

    permission_classes = [CatalogPermission]
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        upload = request.FILES.get("image")
        if upload is None:
            raise serializers.ValidationError({"image": "Choose an image to upload."})
        serializers.ImageField().run_validation(upload)
        plan.image = upload
        plan.save(update_fields=["image"])
        post_message(plan, body="Picture updated.", author=request.user)
        return Response({"image_url": image_url(request, plan)})

    def delete(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        if plan.image:
            plan.image.delete(save=False)
            plan.image = ""
            plan.save(update_fields=["image"])
            post_message(plan, body="Picture removed.", author=request.user)
        return Response(status=204)


class PackageList(ListCreateAPIView):
    serializer_class = PackageCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        packages = Package.objects.select_related("plan").prefetch_related("contents").annotate(
            lead_count=Count("leads", distinct=True),
        )
        plan_id = self.request.query_params.get("plan")
        if plan_id:
            packages = packages.filter(plan_id=plan_id)
        return packages.order_by("plan__name", "price", "id")

    def perform_create(self, serializer):
        package = serializer.save()
        post_message(package, body="Package created.", author=self.request.user)


class PackageDetail(RetrieveUpdateAPIView):
    serializer_class = PackageCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        return PackageList.get_queryset(self)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, PACKAGE_TRACKED_FIELDS)
        package = serializer.save()
        log_changes(package, before, PACKAGE_TRACKED_FIELDS, self.request.user, labels=PACKAGE_FIELD_LABELS)


class ContentList(ListCreateAPIView):
    serializer_class = ContentCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        return Content.objects.annotate(package_count=Count("packages", distinct=True)).order_by("name")


class ContentDetail(RetrieveUpdateAPIView):
    serializer_class = ContentCatalogSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        return ContentList.get_queryset(self)
