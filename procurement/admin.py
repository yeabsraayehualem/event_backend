from django.contrib import admin

from procurement.models import PurchaseOrder, PurchaseOrderLine, PurchaseOrderPayment, Vendor, VendorCategory, VendorDocument


@admin.register(VendorCategory)
class VendorCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "sequence"]
    list_editable = ["sequence"]


class VendorDocumentInline(admin.TabularInline):
    model = VendorDocument
    extra = 0


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "phone", "payment_terms", "active"]
    list_filter = ["category", "active"]
    search_fields = ["name", "phone", "contact_person", "tin_number"]
    inlines = [VendorDocumentInline]


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    readonly_fields = ["subtotal", "tax", "total"]


class PurchaseOrderPaymentInline(admin.TabularInline):
    model = PurchaseOrderPayment
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["reference", "vendor", "event", "status", "total", "order_date"]
    list_filter = ["status", "vendor__category"]
    search_fields = ["reference", "vendor__name", "event__name"]
    readonly_fields = ["reference", "sequence", "subtotal", "tax", "total", "approved_by", "approved_at"]
    inlines = [PurchaseOrderLineInline, PurchaseOrderPaymentInline]
