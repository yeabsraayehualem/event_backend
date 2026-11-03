"""Expenses: the money actually spent, as event costs (linked to an event) or overhead."""

from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from chatter.tracking import log_changes, post_message, snapshot
from event.models import Event
from finance.models import Expense, ExpenseCategory
from procurement.models import PurchaseOrder, Vendor, money
from utils.permissions import IsFinance

EXPENSE_TRACKED_FIELDS = ["date", "category", "description", "event", "vendor", "payee", "amount", "tax", "payment_method", "receipt_number"]
BILLABLE_STATUSES = PurchaseOrder.COMMITTED_STATUSES


def billed_total(order, exclude=None):
    bills = order.bills.all()
    if exclude is not None and exclude.pk:
        bills = bills.exclude(pk=exclude.pk)
    return money(bills.aggregate(value=Sum("total"))["value"] or 0)


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    event_name = serializers.CharField(source="event.name", read_only=True, allow_null=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, allow_null=True)
    purchase_order_reference = serializers.CharField(source="purchase_order.reference", read_only=True, allow_null=True)
    scheduled_payment_label = serializers.CharField(source="scheduled_payment.label", read_only=True, allow_null=True)
    payment_method_label = serializers.CharField(source="get_payment_method_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    receipt_url = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "reference", "date", "category", "category_name", "description", "source", "source_label",
            "event", "event_name", "vendor", "vendor_name", "purchase_order", "purchase_order_reference",
            "scheduled_payment", "scheduled_payment_label", "payee", "amount", "tax", "total",
            "payment_method", "payment_method_label", "receipt_number", "receipt_url", "notes", "shift",
            "created_by_name", "created_at",
        ]
        read_only_fields = ["id", "reference", "source", "total", "shift", "created_at"]
        extra_kwargs = {
            "category": {"queryset": ExpenseCategory.objects.filter(active=True)},
            "purchase_order": {"queryset": PurchaseOrder.objects.select_related("event", "vendor")},
            # validate() explains which bill already paid it; the database still enforces uniqueness.
            "scheduled_payment": {"validators": []},
        }

    def get_receipt_url(self, expense):
        if not expense.receipt:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(expense.receipt.url) if request else expense.receipt.url

    def get_created_by_name(self, expense):
        user = expense.created_by
        return (user.get_full_name() or user.phone) if user else None

    def validate_description(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Say what the money was spent on.")
        return value

    def validate_tax(self, value):
        if value < 0:
            raise serializers.ValidationError("Tax can't be negative.")
        return value

    def validate(self, attrs):
        current = lambda name: attrs[name] if name in attrs else getattr(self.instance, name, None)
        order = current("purchase_order")
        scheduled = current("scheduled_payment")

        if self.instance and self.instance.purchase_order_id and "purchase_order" in attrs and attrs["purchase_order"] != self.instance.purchase_order:
            raise serializers.ValidationError({"purchase_order": "A vendor bill can't be moved to another purchase order. Delete it and record a new one."})

        if self.instance and self.instance.payslip_id:
            changed = [name for name in ("amount", "tax", "event", "purchase_order") if name in attrs and attrs[name] != getattr(self.instance, name)]
            if changed:
                raise serializers.ValidationError({"detail": f"This expense comes from payroll ({self.instance.payslip.run.reference}). Its amount can't be changed here."})
        elif self.instance and self.instance.shift_id:
            changed = [name for name in ("amount", "tax", "event", "purchase_order") if name in attrs and attrs[name] != getattr(self.instance, name)]
            if changed:
                raise serializers.ValidationError({"detail": "This is a crew payout. Change the shift instead: delete this expense, fix the shift, and pay it again."})

        if order is None:
            if scheduled is not None:
                raise serializers.ValidationError({"scheduled_payment": "Choose the purchase order this payment belongs to."})
            return attrs

        if order.status not in BILLABLE_STATUSES:
            raise serializers.ValidationError({"purchase_order": f"{order.reference} is {order.get_status_display().lower()}. Only approved or received orders can be billed."})
        if scheduled is not None:
            if scheduled.order_id != order.id:
                raise serializers.ValidationError({"scheduled_payment": "That payment belongs to a different purchase order."})
            already = getattr(scheduled, "bill", None)  # reverse one-to-one; None when unpaid
            if already is not None and already.pk != getattr(self.instance, "pk", None):
                raise serializers.ValidationError({"scheduled_payment": f"“{scheduled.label}” is already paid by {already.reference}."})

        # A bill always belongs to the order's event and vendor.
        attrs["event"], attrs["vendor"] = order.event, order.vendor
        total = current("amount") + (current("tax") or Decimal("0.00"))
        remaining = order.total - billed_total(order, exclude=self.instance)
        if total > remaining:
            raise serializers.ValidationError({"amount": f"Only {remaining:,.2f} is left to bill on {order.reference} (order total {order.total:,.2f})."})
        return attrs

    def create(self, validated_data):
        if validated_data.get("purchase_order"):
            validated_data["source"] = Expense.Source.PURCHASE_ORDER
        return super().create(validated_data)


def _filtered(request):
    queryset = Expense.objects.select_related("category", "event", "vendor", "purchase_order", "scheduled_payment", "created_by")
    params = request.query_params
    for name in ("start_date", "end_date"):
        if params.get(name) and not parse_date(params[name]):
            raise ValidationError({name: "Use YYYY-MM-DD."})
    if params.get("start_date"):
        queryset = queryset.filter(date__gte=params["start_date"])
    if params.get("end_date"):
        queryset = queryset.filter(date__lte=params["end_date"])
    if params.get("category"):
        queryset = queryset.filter(category_id=params["category"])
    if params.get("event"):
        queryset = queryset.filter(event_id=params["event"])
    if params.get("purchase_order"):
        queryset = queryset.filter(purchase_order_id=params["purchase_order"])
    if params.get("scope") == "overhead":
        queryset = queryset.filter(event__isnull=True)
    elif params.get("scope") == "event":
        queryset = queryset.filter(event__isnull=False)
    return queryset


class ExpenseList(ListCreateAPIView):
    serializer_class = ExpenseSerializer
    permission_classes = [IsFinance]

    def get_queryset(self):
        return _filtered(self.request)

    def perform_create(self, serializer):
        expense = serializer.save(created_by=self.request.user)
        post_message(expense, body=f"Expense {expense.reference} recorded.", author=self.request.user)
        if expense.purchase_order_id:
            label = f" for “{expense.scheduled_payment.label}”" if expense.scheduled_payment_id else ""
            post_message(expense.purchase_order, body=f"Bill {expense.reference} of {expense.total:,.2f} recorded{label}.", author=self.request.user)


class ExpenseDetail(RetrieveUpdateDestroyAPIView):
    serializer_class = ExpenseSerializer
    permission_classes = [IsFinance]

    def get_queryset(self):
        return _filtered(self.request)

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, EXPENSE_TRACKED_FIELDS)
        expense = serializer.save()
        log_changes(expense, before, EXPENSE_TRACKED_FIELDS, self.request.user)

    def perform_destroy(self, expense):
        if expense.payslip_id:
            raise ValidationError({"detail": f"This expense was recorded by payroll ({expense.payslip.run.reference}) and can't be deleted on its own."})
        if expense.purchase_order_id:
            post_message(expense.purchase_order, body=f"Bill {expense.reference} of {expense.total:,.2f} deleted.", author=self.request.user)
        if expense.receipt:
            expense.receipt.delete(save=False)
        expense.delete()


class ExpenseReceipt(APIView):
    """POST a receipt file (multipart, field `receipt`) or DELETE it."""

    permission_classes = [IsFinance]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        upload = request.FILES.get("receipt")
        if not upload:
            raise ValidationError({"receipt": "Choose a file to upload."})
        if expense.receipt:
            expense.receipt.delete(save=False)
        expense.receipt = upload
        expense.save(update_fields=["receipt"])
        post_message(expense, body="Receipt attached.", author=request.user)
        return Response(ExpenseSerializer(expense, context={"request": request}).data)

    def delete(self, request, pk):
        expense = get_object_or_404(Expense, pk=pk)
        if expense.receipt:
            expense.receipt.delete(save=False)
            expense.receipt = ""
            expense.save(update_fields=["receipt"])
            post_message(expense, body="Receipt removed.", author=request.user)
        return Response(ExpenseSerializer(expense, context={"request": request}).data)


class ExpenseOptions(APIView):
    """Dropdown data for the expense form, including what is still left to bill on each order."""

    permission_classes = [IsFinance]

    def get(self, request):
        orders = (
            PurchaseOrder.objects.filter(status__in=BILLABLE_STATUSES)
            .select_related("vendor", "event").prefetch_related("payment_schedule__bill", "bills")
        )
        return Response({
            "categories": list(ExpenseCategory.objects.filter(active=True).values("id", "name")),
            "events": [
                {"id": e.id, "name": e.name, "event_date": e.event_date.isoformat()}
                for e in Event.objects.order_by("-event_date", "-id")
            ],
            "vendors": list(Vendor.objects.filter(active=True).values("id", "name")),
            "payment_methods": [{"value": v, "label": label} for v, label in Expense.PaymentMethod.choices],
            "purchase_orders": [
                {
                    "id": order.id,
                    "reference": order.reference,
                    "vendor_name": order.vendor.name,
                    "event_name": order.event.name,
                    "subtotal": str(order.subtotal),
                    "total": str(order.total),
                    "remaining": str(order.total - billed_total(order)),
                    "payments": [
                        {"id": p.id, "label": p.label, "amount": str(p.amount), "due_date": p.due_date.isoformat() if p.due_date else None,
                         "bill_id": getattr(getattr(p, "bill", None), "id", None)}
                        for p in order.payment_schedule.all()
                    ],
                }
                for order in orders
            ],
        })
