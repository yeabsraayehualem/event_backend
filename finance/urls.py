from django.urls import path

from finance.views import CustomerInvoiceDetail, CustomerInvoiceList, InvoiceEditorOptions

urlpatterns = [
    path("invoice-editor-options/", InvoiceEditorOptions.as_view(), name="invoice-editor-options"),
    path("invoices/", CustomerInvoiceList.as_view(), name="invoice-list-create"),
    path("invoices/<int:pk>/", CustomerInvoiceDetail.as_view(), name="invoice-detail"),
]
