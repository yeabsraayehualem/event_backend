from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import DestroyAPIView, ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from chatter.tracking import log_changes, post_message, snapshot
from event.models import Event
from finance.models import TaxRate
from procurement.models import PurchaseOrder, PurchaseOrderLine, Vendor, VendorCategory, VendorDocument
from procurement.serializers import (
    PurchaseOrderListSerializer, PurchaseOrderSerializer, VendorCategorySerializer, VendorDocumentSerializer,
    VendorListSerializer, VendorSerializer, event_budget_summary,
)
from utils.permissions import ProcurementPermission, can_approve_purchases, can_set_event_budget

VENDOR_TRACKED_FIELDS = [
    "name", "category", "contact_person", "phone", "email", "tin_number", "license_number",
    "payment_terms", "bank_name", "bank_account", "active",
]
ORDER_TRACKED_FIELDS = ["vendor", "delivery_at", "delivery_location", "total"]

Status = PurchaseOrder.Status


def _choices(choices):
    return [{"value": value, "label": label} for value, label in choices]


class ProcurementOptions(APIView):
    """Everything the vendor and purchase order forms need to fill their dropdowns."""

    permission_classes = [ProcurementPermission]

    def get(self, request):
        events = Event.objects.select_related("customer").exclude(status=Event.Status.CANCELLED).order_by("-event_date", "-id")
        vendors = Vendor.objects.filter(active=True).select_related("category")
        return Response({
            "categories": list(VendorCategory.objects.values("id", "name")),
            "vendors": [
                {"id": v.id, "name": v.name, "category": v.category.name, "payment_terms": v.get_payment_terms_display()}
                for v in vendors
            ],
            "events": [
                {"id": e.id, "name": e.name, "customer": e.customer.name, "event_date": e.event_date.isoformat(), "location": e.location}
                for e in events
            ],
            "tax_profiles": list(TaxRate.objects.filter(active=True).values("id", "name", "kind", "rate", "inclusive")),
            "line_kinds": _choices(PurchaseOrderLine.Kind.choices),
            "payment_terms": _choices(Vendor.PaymentTerms.choices),
            "document_kinds": _choices(VendorDocument.Kind.choices),
            "statuses": _choices(Status.choices),
            "can_approve": can_approve_purchases(request.user),
            "can_set_budget": can_set_event_budget(request.user),
        })


class VendorCategoryList(ListCreateAPIView):
    serializer_class = VendorCategorySerializer
    permission_classes = [ProcurementPermission]

    def get_queryset(self):
        return VendorCategory.objects.annotate(vendor_count=Count("vendors"))


class VendorList(ListCreateAPIView):
    permission_classes = [ProcurementPermission]

    def get_serializer_class(self):
        return VendorSerializer if self.request.method == "POST" else VendorListSerializer

    def get_queryset(self):
        committed = Q(purchase_orders__status__in=PurchaseOrder.COMMITTED_STATUSES)
        queryset = Vendor.objects.select_related("category").annotate(
            order_count=Count("purchase_orders", filter=~Q(purchase_orders__status=Status.CANCELLED), distinct=True),
            committed_total=Coalesce(Sum("purchase_orders__total", filter=committed), Value(Decimal("0.00")), output_field=DecimalField()),
        )
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category_id=category)
        return queryset

    def perform_create(self, serializer):
        vendor = serializer.save()
        post_message(vendor, body="Vendor created.", author=self.request.user)


class VendorDetail(RetrieveUpdateAPIView):
    serializer_class = VendorSerializer
    permission_classes = [ProcurementPermission]
    queryset = Vendor.objects.select_related("category").prefetch_related("documents")

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, VENDOR_TRACKED_FIELDS)
        vendor = serializer.save()
        log_changes(vendor, before, VENDOR_TRACKED_FIELDS, self.request.user)


class VendorDocuments(ListCreateAPIView):
    serializer_class = VendorDocumentSerializer
    permission_classes = [ProcurementPermission]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return VendorDocument.objects.filter(vendor_id=self.kwargs["vendor_pk"])

    def perform_create(self, serializer):
        vendor = get_object_or_404(Vendor, pk=self.kwargs["vendor_pk"])
        document = serializer.save(vendor=vendor, uploaded_by=self.request.user)
        post_message(vendor, body=f"{document.get_kind_display()} uploaded.", author=self.request.user)


class VendorDocumentDetail(DestroyAPIView):
    permission_classes = [ProcurementPermission]

    def get_queryset(self):
        return VendorDocument.objects.filter(vendor_id=self.kwargs["vendor_pk"])

    def perform_destroy(self, document):
        post_message(document.vendor, body=f"{document.get_kind_display()} removed.", author=self.request.user)
        document.file.delete(save=False)
        document.delete()


class PurchaseOrderList(ListCreateAPIView):
    permission_classes = [ProcurementPermission]

    def get_serializer_class(self):
        return PurchaseOrderSerializer if self.request.method == "POST" else PurchaseOrderListSerializer

    def get_queryset(self):
        queryset = PurchaseOrder.objects.select_related("vendor__category", "event")
        params = self.request.query_params
        if params.get("event"):
            queryset = queryset.filter(event_id=params["event"])
        if params.get("vendor"):
            queryset = queryset.filter(vendor_id=params["vendor"])
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        return queryset

    def perform_create(self, serializer):
        order = serializer.save(created_by=self.request.user)
        post_message(order, body=f"Purchase order {order.reference} created for {order.event.name}.", author=self.request.user)


class PurchaseOrderDetail(RetrieveUpdateAPIView):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [ProcurementPermission]
    queryset = PurchaseOrder.objects.select_related("vendor", "event", "created_by", "approved_by").prefetch_related(
        "lines__tax_profiles", "payment_schedule",
    )

    def perform_update(self, serializer):
        before = snapshot(serializer.instance, ORDER_TRACKED_FIELDS)
        lines_before = _lines_signature(serializer.instance)
        order = serializer.save()
        lines_changed = _lines_signature(order) != lines_before
        message = log_changes(order, before, ORDER_TRACKED_FIELDS, self.request.user, body="Lines updated." if lines_changed else "")
        if lines_changed and message is None:
            post_message(order, body="Lines updated.", author=self.request.user)


def _lines_signature(order):
    return [
        (line.kind, line.description, str(line.quantity), str(line.unit_price), sorted(t.pk for t in line.tax_profiles.all()))
        for line in PurchaseOrderLine.objects.filter(order=order).prefetch_related("tax_profiles")
    ]


class PurchaseOrderTransition(APIView):
    """Move an order through its workflow: POST {"action": "submit" | "approve" | "reject" | "receive" | "cancel"}.

    Approving is limited to finance, admins and super users. Approving past the event's cost
    budget needs `"confirm_over_budget": true` so nobody overspends by accident.
    """

    permission_classes = [ProcurementPermission]

    # action: (allowed from, moves to, needs approver role)
    TRANSITIONS = {
        "submit": ({Status.DRAFT}, Status.SUBMITTED, False),
        "approve": ({Status.SUBMITTED}, Status.APPROVED, True),
        "reject": ({Status.SUBMITTED, Status.APPROVED}, Status.DRAFT, True),
        "receive": ({Status.APPROVED}, Status.RECEIVED, False),
        "cancel": ({Status.DRAFT, Status.SUBMITTED, Status.APPROVED}, Status.CANCELLED, False),
    }

    @transaction.atomic
    def post(self, request, pk):
        order = get_object_or_404(PurchaseOrder.objects.select_for_update().select_related("event", "vendor"), pk=pk)
        action = request.data.get("action")
        if action not in self.TRANSITIONS:
            raise ValidationError({"action": f"Choose one of: {', '.join(self.TRANSITIONS)}."})
        allowed_from, target, approver_only = self.TRANSITIONS[action]
        reason = str(request.data.get("reason", "")).strip()

        if order.status not in allowed_from:
            allowed = " or ".join(sorted(Status(value).label.lower() for value in allowed_from))
            raise ValidationError({"detail": f"Only {allowed} orders can use “{action}”; {order.reference} is {order.get_status_display().lower()}."})
        # Cancelling an order that is already committed is an approver decision too.
        if (approver_only or (action == "cancel" and order.status == Status.APPROVED)) and not can_approve_purchases(request.user):
            raise PermissionDenied("Only finance, admins or super users can do this.")
        if action in {"reject", "cancel"} and not reason:
            raise ValidationError({"reason": "Give a reason so the team knows what to change."})

        if action in {"reject", "cancel"} and order.bills.exists():
            raise ValidationError({"detail": f"{order.reference} already has vendor bills recorded. Delete those expenses first."})
        if action == "submit" and not order.lines.exists():
            raise ValidationError({"detail": "Add at least one line before submitting."})
        if action == "approve":
            self._check_budget(order, request.data.get("confirm_over_budget") is True)

        old_label = order.get_status_display()
        order.status = target
        fields = ["status"]
        if action == "approve":
            order.approved_by, order.approved_at = request.user, timezone.now()
            fields += ["approved_by", "approved_at"]
        elif action == "reject":
            order.approved_by, order.approved_at = None, None
            fields += ["approved_by", "approved_at"]
        order.save(update_fields=fields)

        body = {
            "submit": "Submitted for approval.",
            "approve": f"Approved. {order.total:,.2f} committed against {order.event.name}.",
            "reject": f"Sent back to draft: {reason}",
            "receive": "Goods/services received.",
            "cancel": f"Cancelled: {reason}",
        }[action]
        post_message(order, body=body, author=request.user, changes=[("status", "Status", old_label, order.get_status_display())])

        order = PurchaseOrderDetail.queryset.get(pk=order.pk)
        return Response(PurchaseOrderSerializer(order, context={"request": request}).data)

    @staticmethod
    def _check_budget(order, confirmed):
        event = order.event
        if event.status == Event.Status.CANCELLED:
            raise ValidationError({"detail": "The event is cancelled, so this order can't be approved."})
        if event.cost_budget is None:
            return
        committed = Decimal(event_budget_summary(event, exclude_order=order)["committed"])
        over_by = committed + order.total - event.cost_budget
        if over_by > 0 and not confirmed:
            raise ValidationError({
                "detail": f"Approving this order puts {event.name} {over_by:,.2f} over its cost budget of {event.cost_budget:,.2f}.",
                "over_budget": str(over_by),
            })


class EventProcurementSummary(APIView):
    """GET an event's budget and spend; PATCH {"cost_budget": "…"} to set the budget."""

    permission_classes = [ProcurementPermission]

    def get(self, request, event_pk):
        event = get_object_or_404(Event, pk=event_pk)
        return Response(self._payload(request, event))

    def patch(self, request, event_pk):
        if not can_set_event_budget(request.user):
            raise PermissionDenied("Only event managers, finance, admins or super users can set the budget.")
        event = get_object_or_404(Event, pk=event_pk)
        raw = request.data.get("cost_budget")
        if raw in (None, ""):
            value = None
        else:
            try:
                value = Decimal(str(raw)).quantize(Decimal("0.01"))
            except InvalidOperation:
                raise ValidationError({"cost_budget": "Enter a number."})
            if value < 0:
                raise ValidationError({"cost_budget": "The budget can't be negative."})
        before = snapshot(event, ["cost_budget"])
        event.cost_budget = value
        event.save(update_fields=["cost_budget"])
        log_changes(event, before, ["cost_budget"], request.user)
        return Response(self._payload(request, event), status=status.HTTP_200_OK)

    @staticmethod
    def _payload(request, event):
        orders = event.purchase_orders.select_related("vendor__category").exclude(status=Status.CANCELLED)
        return {
            **event_budget_summary(event),
            "can_set_budget": can_set_event_budget(request.user),
            "orders": PurchaseOrderListSerializer(orders, many=True).data,
        }
