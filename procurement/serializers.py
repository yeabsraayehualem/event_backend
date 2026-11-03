from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import serializers

from event.models import Event
from finance.models import TaxRate
from procurement.models import (
    PurchaseOrder, PurchaseOrderLine, PurchaseOrderPayment, Vendor, VendorCategory, VendorDocument, money,
)


def event_budget_summary(event, exclude_order=None):
    """Budget, committed (approved/received) and pending (waiting approval) spend for an event."""
    orders = event.purchase_orders.all()
    if exclude_order is not None:
        orders = orders.exclude(pk=exclude_order.pk)
    totals = orders.aggregate(
        committed=Sum("total", filter=Q(status__in=PurchaseOrder.COMMITTED_STATUSES)),
        pending=Sum("total", filter=Q(status=PurchaseOrder.Status.SUBMITTED)),
    )
    committed = money(totals["committed"] or 0)
    pending = money(totals["pending"] or 0)
    budget = event.cost_budget
    return {
        "event_id": event.id,
        "event_name": event.name,
        "budget": None if budget is None else str(budget),
        "committed": str(committed),
        "pending": str(pending),
        "remaining": None if budget is None else str(budget - committed),
    }


class VendorCategorySerializer(serializers.ModelSerializer):
    vendor_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = VendorCategory
        fields = ["id", "name", "sequence", "vendor_count"]


class VendorDocumentSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    file_name = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = VendorDocument
        fields = ["id", "kind", "kind_label", "file", "file_name", "file_url", "expires_on", "is_expired", "uploaded_at"]
        read_only_fields = ["id", "uploaded_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_file_name(self, document):
        return document.file.name.rsplit("/", 1)[-1] if document.file else ""

    def get_file_url(self, document):
        if not document.file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(document.file.url) if request else document.file.url


class VendorListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    order_count = serializers.IntegerField(read_only=True, default=0)
    committed_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=Decimal("0.00"))

    class Meta:
        model = Vendor
        fields = ["id", "name", "category", "category_name", "contact_person", "phone", "email", "active", "order_count", "committed_total"]


class VendorSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    payment_terms_label = serializers.CharField(source="get_payment_terms_display", read_only=True)
    documents = VendorDocumentSerializer(many=True, read_only=True)
    purchase_orders = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id", "name", "category", "category_name", "contact_person", "phone", "email", "address",
            "tin_number", "license_number", "payment_terms", "payment_terms_label", "bank_name", "bank_account",
            "notes", "active", "created_at", "documents", "purchase_orders",
        ]
        read_only_fields = ["id", "created_at"]

    def get_purchase_orders(self, vendor):
        """Engagement history: every order placed with this vendor, newest first."""
        return [
            {
                "id": order.id, "reference": order.reference, "event_id": order.event_id, "event_name": order.event.name,
                "event_date": order.event.event_date.isoformat(), "status": order.status,
                "status_label": order.get_status_display(), "total": str(order.total),
            }
            for order in vendor.purchase_orders.select_related("event").order_by("-order_date", "-sequence")
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Give the vendor a name.")
        return value


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    tax_profile_ids = serializers.PrimaryKeyRelatedField(
        source="tax_profiles", many=True, queryset=TaxRate.objects.filter(active=True), required=False,
    )

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "kind", "kind_label", "description", "quantity", "unit_price", "tax_profile_ids", "subtotal", "tax", "total"]
        read_only_fields = ["id", "subtotal", "tax", "total"]

    def validate(self, attrs):
        profiles = attrs.get("tax_profiles", [])
        if any(profile.kind == TaxRate.Kind.EXEMPT for profile in profiles) and len(profiles) > 1:
            raise serializers.ValidationError({"tax_profile_ids": "An exempt profile cannot be combined with other taxes."})
        return attrs


class PurchaseOrderPaymentSerializer(serializers.ModelSerializer):
    bill = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderPayment
        fields = ["id", "label", "amount", "due_date", "bill"]
        read_only_fields = ["id"]

    def get_bill(self, payment):
        bill = getattr(payment, "bill", None)
        return {"id": bill.id, "reference": bill.reference, "date": bill.date.isoformat()} if bill else None


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    vendor_category = serializers.CharField(source="vendor.category.name", read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True)
    event_date = serializers.DateField(source="event.event_date", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "reference", "vendor", "vendor_name", "vendor_category", "event", "event_name", "event_date",
            "order_date", "delivery_at", "status", "status_label", "total",
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    vendor_payment_terms = serializers.CharField(source="vendor.get_payment_terms_display", read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True)
    event_date = serializers.DateField(source="event.event_date", read_only=True)
    event_location = serializers.CharField(source="event.location", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    lines = PurchaseOrderLineSerializer(many=True)
    payment_schedule = PurchaseOrderPaymentSerializer(many=True, required=False)
    budget = serializers.SerializerMethodField()
    can_approve = serializers.SerializerMethodField()
    bills = serializers.SerializerMethodField()
    billed_total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "reference", "vendor", "vendor_name", "vendor_payment_terms", "event", "event_name", "event_date",
            "event_location", "status", "status_label", "order_date", "delivery_at", "delivery_location", "notes",
            "subtotal", "tax", "total", "created_by_name", "approved_by_name", "approved_at", "lines",
            "payment_schedule", "budget", "can_approve", "bills", "billed_total",
        ]
        read_only_fields = [
            "id", "reference", "status", "subtotal", "tax", "total", "created_by_name", "approved_by_name", "approved_at",
        ]
        extra_kwargs = {
            "vendor": {"queryset": Vendor.objects.filter(active=True)},
            "event": {"queryset": Event.objects.exclude(status=Event.Status.CANCELLED)},
        }

    @staticmethod
    def _name(user):
        return (user.get_full_name() or user.phone) if user else None

    def get_created_by_name(self, order):
        return self._name(order.created_by)

    def get_approved_by_name(self, order):
        return self._name(order.approved_by)

    def get_budget(self, order):
        return event_budget_summary(order.event)

    def get_bills(self, order):
        return [
            {
                "id": bill.id, "reference": bill.reference, "date": bill.date.isoformat(), "total": str(bill.total),
                "payment_method": bill.get_payment_method_display(),
                "scheduled_payment": bill.scheduled_payment.label if bill.scheduled_payment_id else None,
            }
            for bill in order.bills.select_related("scheduled_payment").order_by("date", "id")
        ]

    def get_billed_total(self, order):
        return str(money(order.bills.aggregate(value=Sum("total"))["value"] or 0))

    def get_can_approve(self, order):
        from utils.permissions import can_approve_purchases

        request = self.context.get("request")
        return bool(request and can_approve_purchases(request.user))

    def validate(self, attrs):
        if self.instance is not None and not self.instance.is_editable:
            raise serializers.ValidationError(
                f"{self.instance.reference} is {self.instance.get_status_display().lower()}, so it can't be edited. "
                "Cancel it and raise a new order, or ask an approver to send it back to draft."
            )
        if self.instance is not None and "event" in attrs and attrs["event"].pk != self.instance.event_id:
            raise serializers.ValidationError({"event": "A purchase order can't be moved to another event."})
        if (self.instance is None or "lines" in attrs) and not attrs.get("lines"):
            raise serializers.ValidationError({"lines": "Add at least one line."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        schedule = validated_data.pop("payment_schedule", [])
        order = PurchaseOrder.objects.create(**validated_data)
        self._replace_lines(order, lines)
        self._replace_schedule(order, schedule)
        return order

    @transaction.atomic
    def update(self, order, validated_data):
        lines = validated_data.pop("lines", None)
        schedule = validated_data.pop("payment_schedule", None)
        validated_data.pop("event", None)
        for field, value in validated_data.items():
            setattr(order, field, value)
        order.save()
        if lines is not None:
            self._replace_lines(order, lines)
        if schedule is not None:
            self._replace_schedule(order, schedule)
        return order

    @staticmethod
    def _replace_lines(order, lines):
        order.lines.all().delete()
        for position, values in enumerate(lines):
            profiles = values.pop("tax_profiles", [])
            line = PurchaseOrderLine.objects.create(order=order, sequence=position, **values)
            line.tax_profiles.set(profiles)
            line.recalculate()
        order.recalculate_totals()

    @staticmethod
    def _replace_schedule(order, schedule):
        order.payment_schedule.all().delete()
        PurchaseOrderPayment.objects.bulk_create([
            PurchaseOrderPayment(order=order, sequence=position, **values) for position, values in enumerate(schedule)
        ])
        scheduled = sum((item["amount"] for item in schedule), Decimal("0.00"))
        if schedule and scheduled != order.total:
            raise serializers.ValidationError({
                "payment_schedule": f"The payment schedule adds up to {scheduled:,.2f} but the order total is {order.total:,.2f}.",
            })
