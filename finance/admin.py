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
