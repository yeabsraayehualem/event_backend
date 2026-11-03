"""Vendors and the purchase orders issued to them for a specific event (PRD VND-001, VND-002)."""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Max, Sum
from django.utils import timezone

from finance.models import TaxRate

CENT = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_line_amounts(base, taxes):
    """Split a line amount into (untaxed, tax, total) for the given tax profiles.

    `taxes` are objects with `kind`, `rate` and `inclusive` (TaxRate or a snapshot of one).
    Inclusive VAT is already inside `base`; other taxes are added, and withholding is deducted
    from what is paid to the vendor. Uses the same rules as customer invoice lines.
    """
    base = money(base)
    included = Decimal("0.00")
    tax_total = Decimal("0.00")
    added = Decimal("0.00")
    for tax in taxes:
        rate = Decimal(tax.rate) / Decimal("100")
        if tax.kind == TaxRate.Kind.EXEMPT:
            continue
        if tax.kind == TaxRate.Kind.VAT and tax.inclusive:
            amount = money(base * rate / (1 + rate))
            included += amount
        else:
            amount = money(base * rate)
            if tax.kind == TaxRate.Kind.WITHHOLDING:
                amount = -amount
            added += amount
        tax_total += amount
    return base - included, tax_total, base + added


class VendorCategory(models.Model):
    """What a vendor supplies, e.g. Catering, Photography, Equipment rental."""

    name = models.CharField(max_length=100, unique=True)
    sequence = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sequence", "name"]
        verbose_name_plural = "vendor categories"

    def __str__(self):
        return self.name


class Vendor(models.Model):
    class PaymentTerms(models.TextChoices):
        ADVANCE = "advance", "Full payment in advance"
        ON_DELIVERY = "on_delivery", "On delivery"
        NET_7 = "net_7", "7 days after delivery"
        NET_15 = "net_15", "15 days after delivery"
        NET_30 = "net_30", "30 days after delivery"
        MILESTONES = "milestones", "Per payment schedule"

    name = models.CharField(max_length=200)
    category = models.ForeignKey(VendorCategory, on_delete=models.PROTECT, related_name="vendors")
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    tin_number = models.CharField("TIN", max_length=30, blank=True)
    license_number = models.CharField("Business license number", max_length=60, blank=True)
    payment_terms = models.CharField(max_length=20, choices=PaymentTerms.choices, default=PaymentTerms.ON_DELIVERY)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField(max_length=60, blank=True)
    notes = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class VendorDocument(models.Model):
    """Compliance paperwork kept on file: licenses, tax registration, signed contracts."""

    class Kind(models.TextChoices):
        BUSINESS_LICENSE = "business_license", "Business license"
        TAX_REGISTRATION = "tax_registration", "Tax registration (TIN)"
        VAT_CERTIFICATE = "vat_certificate", "VAT certificate"
        CONTRACT = "contract", "Contract"
        OTHER = "other", "Other"

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=30, choices=Kind.choices, default=Kind.OTHER)
    file = models.FileField(upload_to="vendor_documents/")
    expires_on = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["kind", "-uploaded_at"]

    @property
    def is_expired(self):
        return bool(self.expires_on and self.expires_on < timezone.localdate())

    def __str__(self):
        return f"{self.vendor} – {self.get_kind_display()}"


class PurchaseOrder(models.Model):
    """A commitment to a vendor for goods or services on one event.

    Draft → Submitted → Approved → Received. Only drafts can be edited; approved and
    received orders count against the event budget, submitted ones show as pending.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Waiting approval"
        APPROVED = "approved", "Approved"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    COMMITTED_STATUSES = (Status.APPROVED, Status.RECEIVED)

    reference = models.CharField(max_length=20, unique=True, blank=True)
    sequence = models.PositiveIntegerField(default=0)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="purchase_orders")
    event = models.ForeignKey("event.Event", on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField(default=timezone.localdate)
    delivery_at = models.DateTimeField("Delivery time", null=True, blank=True)
    delivery_location = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-order_date", "-sequence"]

    def __str__(self):
        return self.reference

    def save(self, *args, **kwargs):
        if not self.pk and not self.reference:
            year = timezone.localdate().year
            last = PurchaseOrder.objects.filter(reference__startswith=f"PO-{year}-").aggregate(value=Max("sequence"))["value"] or 0
            self.sequence = last + 1
            self.reference = f"PO-{year}-{self.sequence:04d}"
        super().save(*args, **kwargs)

    def recalculate_totals(self):
        totals = self.lines.aggregate(subtotal=Sum("subtotal"), tax=Sum("tax"), total=Sum("total"))
        self.subtotal = money(totals["subtotal"] or 0)
        self.tax = money(totals["tax"] or 0)
        self.total = money(totals["total"] or 0)
        self.save(update_fields=["subtotal", "tax", "total"])

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT


class PurchaseOrderLine(models.Model):
    class Kind(models.TextChoices):
        SERVICE = "service", "Service"
        RENTAL = "rental", "Rental"
        GOODS = "goods", "Goods"

    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SERVICE)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1, validators=[MinValueValidator(Decimal("0.01"))])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    tax_profiles = models.ManyToManyField(TaxRate, blank=True, related_name="+")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["sequence", "id"]

    def recalculate(self):
        self.subtotal, self.tax, self.total = compute_line_amounts(self.quantity * self.unit_price, self.tax_profiles.all())
        self.save(update_fields=["subtotal", "tax", "total"])

    def __str__(self):
        return self.description


class PurchaseOrderPayment(models.Model):
    """A scheduled payment to the vendor, e.g. 50% deposit on signing, balance on delivery."""

    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="payment_schedule")
    sequence = models.PositiveIntegerField(default=0)
    label = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["sequence", "id"]

    def __str__(self):
        return f"{self.label}: {self.amount}"
