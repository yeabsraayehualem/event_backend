from django.urls import path

from finance import expenses
from finance.views import CustomerInvoiceDetail, CustomerInvoiceList, InvoiceEditorOptions

urlpatterns = [
    path("invoice-editor-options/", InvoiceEditorOptions.as_view(), name="invoice-editor-options"),
    path("invoices/", CustomerInvoiceList.as_view(), name="invoice-list-create"),
    path("invoices/<int:pk>/", CustomerInvoiceDetail.as_view(), name="invoice-detail"),
    path("expense-options/", expenses.ExpenseOptions.as_view(), name="expense-options"),
    path("expenses/", expenses.ExpenseList.as_view(), name="expense-list"),
    path("expenses/<int:pk>/", expenses.ExpenseDetail.as_view(), name="expense-detail"),
    path("expenses/<int:pk>/receipt/", expenses.ExpenseReceipt.as_view(), name="expense-receipt"),
]
