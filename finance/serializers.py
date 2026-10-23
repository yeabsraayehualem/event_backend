from django.db import transaction
from rest_framework import serializers

from event.models import Content, Event
from finance.models import CustomerInvoice, InvoiceLines, InvoiceLineTax, TaxRate


class InvoiceListSerializer(serializers.ModelSerializer):
    customer = serializers.CharField(source="customer.name", read_only=True)
    plan = serializers.CharField(source="plan.name", read_only=True)
    package = serializers.CharField(source="package.name", read_only=True, allow_null=True)
    class Meta:
        model = CustomerInvoice
        fields = ["id", "reference", "sequence", "event", "date", "due_date", "total", "status", "customer", "plan", "package"]
        read_only_fields = ["id", "reference", "sequence", "event", "date", "total", "customer", "plan", "package"]

class InvoiceLineSerializer(serializers.ModelSerializer):
    inclusive_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    content_id = serializers.PrimaryKeyRelatedField(source="content", queryset=Content.objects.all(), write_only=True)
    selected_content_id = serializers.IntegerField(source="content_id", read_only=True)
    content_name = serializers.CharField(source="content.name", read_only=True)
    tax_profile_id = serializers.PrimaryKeyRelatedField(
        source="tax_profile", queryset=TaxRate.objects.filter(active=True), required=False, allow_null=True, write_only=True
    )
    tax_profile_name = serializers.CharField(source="tax_profile.name", read_only=True, allow_null=True)
    tax_profile_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=TaxRate.objects.filter(active=True), required=False, write_only=True
    )
    selected_tax_profile_ids = serializers.SerializerMethodField()
    tax_components = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLines
        fields = [
            "id", "content_id", "selected_content_id", "content_name", "tax_profile_id", "tax_profile_name",
            "tax_profile_ids", "selected_tax_profile_ids", "tax_components",
            "inclusive_price", "tax_rate", "price", "tax", "total",
        ]
        read_only_fields = ["id", "tax_rate", "price", "tax", "total"]

    def get_tax_components(self, line):
        return [
            {"name": component.name, "kind": component.kind, "rate": str(component.rate), "amount": str(component.amount)}
            for component in line.tax_components.all()
        ]

    def get_selected_tax_profile_ids(self, line):
        profile_ids = [component.profile_id for component in line.tax_components.all() if component.profile_id]
        if profile_ids:
            return profile_ids
        return [line.tax_profile_id] if line.tax_profile_id else []

    def validate(self, attrs):
        profiles = attrs.get("tax_profile_ids", [])
        if any(profile.kind == TaxRate.Kind.EXEMPT for profile in profiles) and len(profiles) > 1:
            raise serializers.ValidationError({"tax_profile_ids": "An exempt profile cannot be combined with other taxes."})
        return attrs


class CustomerInvoiceSerializer(serializers.ModelSerializer):
    event_id = serializers.PrimaryKeyRelatedField(source="event", queryset=Event.objects.select_related("customer", "plan", "package"), write_only=True)
    event = serializers.PrimaryKeyRelatedField(read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    package_name = serializers.CharField(source="package.name", read_only=True, allow_null=True)
    lines = InvoiceLineSerializer(many=True)
    tax_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = CustomerInvoice
        fields = [
            "id", "reference", "sequence", "event", "event_id", "customer_name", "plan_name",
            "package_name", "milestone_name", "date", "due_date", "total", "status", "lines", "tax_breakdown",
        ]
        read_only_fields = ["id", "reference", "sequence", "event", "customer_name", "plan_name", "package_name", "date", "total", "tax_breakdown"]

    def get_tax_breakdown(self, invoice):
        totals = {}
        for line in invoice.lines.select_related("tax_profile"):
            components = list(line.tax_components.all())
            if components:
                for component in components:
                    kind_label = component.get_kind_display()
                    totals[kind_label] = totals.get(kind_label, 0) + component.amount
            else:
                key = line.tax_profile.get_kind_display() if line.tax_profile_id else TaxRate.Kind.VAT.label
                totals[key] = totals.get(key, 0) + line.tax
        return [{"kind": key, "amount": str(value)} for key, value in sorted(totals.items())]

    def validate(self, attrs):
        event = attrs.get("event")
        if event and self.instance and self.instance.event_id != event.id:
            raise serializers.ValidationError({"event_id": "An invoice cannot be moved to another event."})
        if (self.instance is None or "lines" in attrs) and not attrs.get("lines"):
            raise serializers.ValidationError({"lines": "Add at least one invoice line."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        event = validated_data.pop("event")
        invoice = CustomerInvoice.objects.create(
            event=event,
            customer=event.customer,
            plan=event.plan,
            package=event.package,
            **validated_data,
        )
        for line in lines:
            self._create_line(invoice, line)
        invoice.recalculate_total()
        return invoice

    @staticmethod
    def _create_line(invoice, values):
        profiles = values.pop("tax_profile_ids", [])
        legacy_profile = values.get("tax_profile")
        line = InvoiceLines.objects.create(invoice=invoice, **values)
        selected_profiles = profiles or ([legacy_profile] if legacy_profile else [])
        for profile in selected_profiles:
            InvoiceLineTax.objects.create(
                line=line,
                profile=profile,
                name=profile.name,
                kind=profile.kind,
                rate=profile.rate,
                inclusive=profile.inclusive,
            )
        if selected_profiles:
            line.recalculate_tax()
        return line

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        validated_data.pop("event", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if lines is not None:
            instance.lines.all().delete()
            for line in lines:
                self._create_line(instance, line)
        instance.recalculate_total()
        return instance
