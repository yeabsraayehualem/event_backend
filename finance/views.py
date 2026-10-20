from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView

from finance.models import CustomerInvoice
from finance.serializers import CustomerInvoiceSerializer
from utils.permissions import IsFinanceOrSuper


class CustomerInvoiceList(ListCreateAPIView):
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [IsFinanceOrSuper]

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile").order_by("-date", "-sequence")


class CustomerInvoiceDetail(RetrieveUpdateAPIView):
    serializer_class = CustomerInvoiceSerializer
    permission_classes = [IsFinanceOrSuper]

    def get_queryset(self):
        return CustomerInvoice.objects.select_related(
            "event", "customer", "plan", "package"
        ).prefetch_related("lines__content", "lines__tax_profile")
