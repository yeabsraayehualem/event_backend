from django.contrib import admin
from . import models


admin.site.register(models.CustomerInvoice)
admin.site.register(models.InvoiceLines)
