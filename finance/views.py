from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from event.models import Content
from finance.models import CustomerInvoice, TaxRate
from finance.serializers import CustomerInvoiceSerializer, InvoiceListSerializer
from utils.permissions import IsSalesOrFinanceOrSuper


class CustomerInvoiceList(ListCreateAPIView):
    serializer_class = InvoiceListSerializer
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile").order_by("-date", "-sequence")


class CustomerInvoiceDetail(RetrieveUpdateAPIView):
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile")


class InvoiceEditorOptions(APIView):
    permission_classes = [IsSalesOrFinanceOrSuper]

    def get(self, request):
        contents = Content.objects.order_by("name").values("id", "name")
        tax_profiles = TaxRate.objects.filter(active=True).order_by("name").values(
            "id", "name", "kind", "rate", "inclusive"
        )
        return Response({"contents": list(contents), "tax_profiles": list(tax_profiles)})
