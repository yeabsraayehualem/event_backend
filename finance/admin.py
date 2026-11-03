from django.contrib import admin
from . import models


admin.site.register(models.CustomerInvoice)
admin.site.register(models.InvoiceLines)
admin.site.register(models.InvoiceLineTax)


@admin.register(models.TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "rate", "inclusive", "active")
    list_filter = ("kind", "active", "inclusive")
    list_editable = ("rate", "inclusive", "active")


@admin.register(models.ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sequence", "active")
    list_editable = ("sequence", "active")


@admin.register(models.Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("reference", "date", "category", "description", "event", "amount", "total")
    list_filter = ("category", "source", "payment_method")
    search_fields = ("reference", "description", "payee", "receipt_number")
    readonly_fields = ("reference", "sequence", "total", "created_by", "created_at")
