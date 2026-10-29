from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from event.models import Content
from finance.models import CustomerInvoice, TaxRate
from finance.serializers import CustomerInvoiceSerializer, InvoiceListSerializer
from utils.permissions import IsSalesOrFinanceOrSuper
from chatter.tracking import log_changes, post_message, snapshot

INVOICE_TRACKED_FIELDS = ["status", "due_date", "milestone_name", "total"]


def _lines_signature(invoice):
    return [
        (line.content_id, str(line.inclusive_price), sorted(c.profile_id or 0 for c in line.tax_components.all()))
        for line in invoice.lines.all()
    ]


class CustomerInvoiceList(ListCreateAPIView):
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get_serializer_class(self):
        # Creating needs the event and lines; the list only shows a summary.
        return CustomerInvoiceSerializer if self.request.method == "POST" else InvoiceListSerializer

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile").order_by("-date", "-sequence")

    def perform_create(self, serializer):
        invoice = serializer.save()
        post_message(invoice, body=f"Invoice {invoice.reference} created.", author=self.request.user)


class CustomerInvoiceDetail(RetrieveUpdateAPIView):
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile")

    def perform_update(self, serializer):
        invoice = serializer.instance
        before = snapshot(invoice, INVOICE_TRACKED_FIELDS)
        lines_before = _lines_signature(invoice)
        invoice = serializer.save()
        invoice.refresh_from_db()  # drops the prefetched lines so the new ones are compared
        lines_changed = _lines_signature(invoice) != lines_before
        message = log_changes(
            invoice, before, INVOICE_TRACKED_FIELDS, self.request.user,
            body="Invoice lines updated." if lines_changed else "",
        )
        if lines_changed and message is None:
            post_message(invoice, body="Invoice lines updated.", author=self.request.user)


class InvoiceEditorOptions(APIView):
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get(self, request):
        contents = Content.objects.order_by("name").values("id", "name")
        tax_profiles = TaxRate.objects.filter(active=True).order_by("name").values(
            "id", "name", "kind", "rate", "inclusive"
        )
        return Response({"contents": list(contents), "tax_profiles": list(tax_profiles)})
